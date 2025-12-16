import json
import re

import requests
from bs4 import BeautifulSoup


def _is_recipe_node(node):
    """Return True if this JSON-LD node represents a recipe."""
    if not isinstance(node, dict):
        return False

    type_value = node.get("@type")
    if isinstance(type_value, list):
        return any(str(t).lower() == "recipe" for t in type_value)
    if isinstance(type_value, str):
        return type_value.lower() == "recipe"
    return False


def _find_recipe_in_json(data, max_depth=5):
    """
    Recursively search JSON-LD data for a node whose @type is Recipe.

    This is designed to handle a variety of structures used by different sites,
    including:
    - A single dict with @type == "Recipe"
    - A list of dicts that contains a recipe node
    - Objects that contain an @graph list with a recipe node
    - Objects that contain mainEntity pointing at a recipe node
    """
    if max_depth <= 0 or data is None:
        return None

    if isinstance(data, dict):
        if _is_recipe_node(data):
            return data

        # Common container patterns
        for key in ("@graph", "graph", "mainEntity"):
            if key in data:
                found = _find_recipe_in_json(data[key], max_depth - 1)
                if found:
                    return found

        # Fallback: search all nested dict/list values
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = _find_recipe_in_json(value, max_depth - 1)
                if found:
                    return found

    elif isinstance(data, list):
        for item in data:
            found = _find_recipe_in_json(item, max_depth - 1)
            if found:
                return found

    return None


def scrape_recipe_data(url):
    """
    Scrapes recipe data from a given URL using JSON-LD metadata when available.

    Args:
        url (str): The URL of the recipe page.

    Returns:
        dict: A dictionary containing the recipe's title, ingredients,
              instructions, and URL, or None if scraping fails.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/58.0.3029.110 Safari/537.3"
            )
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching the page: {e}")
        return None

    soup = BeautifulSoup(html_content, "html.parser")
    json_scripts = soup.find_all("script", type="application/ld+json")

    recipe_data = None
    for script in json_scripts:
        raw_json = script.string or script.get_text()
        if not raw_json:
            continue

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            # Some sites put multiple JSON objects or comments in a single script;
            # skip anything we can't decode cleanly.
            continue

        recipe_data = _find_recipe_in_json(data)
        if recipe_data:
            break

    if not recipe_data:
        return None

    title = recipe_data.get("name", "No Title Found")

    # Try to determine a representative image URL.
    image_url = None
    image_field = recipe_data.get("image")
    if isinstance(image_field, str):
        image_url = image_field
    elif isinstance(image_field, list) and image_field:
        first = image_field[0]
        if isinstance(first, str):
            image_url = first
        elif isinstance(first, dict):
            image_url = first.get("url") or first.get("@id")
    elif isinstance(image_field, dict):
        image_url = image_field.get("url") or image_field.get("@id")

    if not image_url:
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = og_image["content"]

    # Try to determine servings from recipeYield when available.
    servings = None
    recipe_yield = recipe_data.get("recipeYield")
    if isinstance(recipe_yield, list) and recipe_yield:
        recipe_yield = recipe_yield[0]
    if isinstance(recipe_yield, (int, float)):
        try:
            servings = int(recipe_yield)
        except (TypeError, ValueError):
            servings = None
    elif isinstance(recipe_yield, str):
        match = re.search(r"(\d+(?:\.\d+)?)", recipe_yield)
        if match:
            try:
                servings = int(float(match.group(1)))
            except ValueError:
                servings = None

    ingredients = recipe_data.get("recipeIngredient", [])
    instructions_list = recipe_data.get("recipeInstructions", [])

    instructions = []

    def _add_instruction_text(step_obj):
        text = ""
        if isinstance(step_obj, dict):
            text = step_obj.get("text") or step_obj.get("name") or ""
        elif isinstance(step_obj, str):
            text = step_obj
        text = (text or "").strip()
        if text:
            instructions.append(text)

    for step in instructions_list:
        if isinstance(step, dict):
            step_type = step.get("@type")
            if step_type == "HowToStep":
                _add_instruction_text(step)
            elif step_type == "HowToSection":
                for sub_step in step.get("itemListElement", []):
                    _add_instruction_text(sub_step)
        else:
            _add_instruction_text(step)

    nutrition_info = None
    raw_nutrition = recipe_data.get("nutrition")
    if isinstance(raw_nutrition, dict):
        # Pick common fields for displaying per-serving info.
        fields = [
            "servingSize",
            "calories",
            "carbohydrateContent",
            "proteinContent",
            "fatContent",
            "saturatedFatContent",
            "cholesterolContent",
            "sodiumContent",
            "fiberContent",
            "sugarContent",
        ]
        nutrition_info = {}
        for key in fields:
            if raw_nutrition.get(key):
                nutrition_info[key] = raw_nutrition[key]
        if not nutrition_info:
            nutrition_info = None

    return {
        "title": title,
        "servings": servings,
        "ingredients": ingredients,
        "instructions": instructions,
        "nutrition": nutrition_info,
        "image_url": image_url,
        "url": url,
    }
