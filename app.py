import re
from datetime import date

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from web_scraper import scrape_recipe_data
from database import (
    load_recipes,
    save_recipes,
    load_meal_plan,
    save_meal_plan,
    load_recipe_sites,
    save_recipe_sites,
)

TAGS = ["Quick", "Kid-friendly", "Spicy"]

DAYS_OF_WEEK = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Curated list of recipe sites that work well with the scraper.
DEFAULT_RECIPE_SITES = [
    {"name": "Allrecipes", "url": "https://www.allrecipes.com/"},
    {"name": "Delish", "url": "https://www.delish.com/"},
    {"name": "BBC Good Food", "url": "https://www.bbcgoodfood.com/"},
    {"name": "Simply Recipes", "url": "https://www.simplyrecipes.com/"},
    {"name": "Cookie and Kate", "url": "https://cookieandkate.com/"},
]

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

@app.route('/')
def index():
    recipes = load_recipes()
    categories = sorted(["Breakfast", "Lunch", "Dinner", "Beef", "Chicken", "Fish", "Desserts", "Vegetarian", "Pasta", "Soups", "Other", "Appetizer", "Salad", "Side Dish", "Vegan", "Gluten-Free", "Mexican", "Italian", "Indian", "Chinese", "Japanese"])
    plan = load_meal_plan() or {}
    recipe_sites = load_recipe_sites(DEFAULT_RECIPE_SITES)
    # Ensure all days are present
    for day in DAYS_OF_WEEK:
        plan.setdefault(day, None)
    recipe_map = {r['id']: r for r in recipes}
    return render_template(
        'index.html',
        recipes=recipes,
        categories=categories,
        plan=plan,
        days=DAYS_OF_WEEK,
        recipe_map=recipe_map,
        recipe_sites=recipe_sites,
    )

@app.route('/add_recipe', methods=['POST'])
def add_recipe():
    url = request.form.get('url')
    categories = request.form.getlist('category')
    if not url:
        return jsonify({'success': False, 'message': 'URL is required.'}), 400

    scraped_data = scrape_recipe_data(url)
    if not scraped_data:
        return jsonify({'success': False, 'message': 'Failed to scrape the recipe.'}), 400

    recipes = load_recipes()
    new_id = max([r['id'] for r in recipes] + [0]) + 1
    
    new_recipe = {
        'id': new_id,
        'title': scraped_data['title'],
        'favorite': False,
        'servings': scraped_data.get('servings'),
        'notes': '',
        'rating': None,
        'cooked_count': 0,
        'last_cooked': None,
        'made_again': False,
        'category': categories,
        'tags': [],
        'ingredients': scraped_data['ingredients'],
        'instructions': scraped_data['instructions'],
        'nutrition': scraped_data.get('nutrition'),
        'image_url': scraped_data.get('image_url'),
        'url': scraped_data['url']
    }
    
    recipes.insert(0, new_recipe)
    save_recipes(recipes)
    
    return redirect(url_for('index'))


@app.route('/add_recipe_site', methods=['POST'])
def add_recipe_site():
    """
    Add a new recipe website link to the list shown on the homepage.
    """
    name = (request.form.get('site_name') or '').strip()
    url = (request.form.get('site_url') or '').strip()

    if not name or not url:
        flash('Site name and URL are required to add a recipe website.')
        return redirect(url_for('index'))

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    recipe_sites = load_recipe_sites(DEFAULT_RECIPE_SITES)

    # Avoid duplicates by URL (case-insensitive).
    normalized_url = url.rstrip('/').lower()
    for site in recipe_sites:
        existing_url = (site.get('url') or '').rstrip('/').lower()
        if existing_url == normalized_url:
            flash('This recipe website is already in your list.')
            break
    else:
        recipe_sites.append({"name": name, "url": url})
        save_recipe_sites(recipe_sites)
        flash(f'Added recipe website: {name}')

    return redirect(url_for('index'))

def _parse_quantity_and_rest(text):
    """
    Parse a leading numeric quantity from an ingredient line.

    Examples:
        \"1 1/2 cups flour\" -> (1.5, \" cups flour\")
        \"1/4 cup sugar\" -> (0.25, \" cup sugar\")
        \"0.5 medium onion\" -> (0.5, \" medium onion\")
    """
    pattern = r'^\s*(\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)(.*)$'
    match = re.match(pattern, text)
    if not match:
        return None, text

    qty_str, rest = match.group(1), match.group(2)

    try:
        if ' ' in qty_str and '/' in qty_str:
            # Mixed number, e.g., \"1 1/2\"
            whole_str, frac_str = qty_str.split()
            num_str, den_str = frac_str.split('/')
            qty = float(whole_str) + float(num_str) / float(den_str)
        elif '/' in qty_str:
            # Simple fraction, e.g., \"1/2\"
            num_str, den_str = qty_str.split('/')
            qty = float(num_str) / float(den_str)
        else:
            qty = float(qty_str)
    except (ValueError, ZeroDivisionError):
        return None, text

    return qty, rest


def _format_quantity(value):
    """Format a numeric quantity as a friendly mixed number rounded to 1/8."""
    if value is None:
        return ''

    # Round to nearest 1/8 to avoid long decimals.
    n_eighths = round(value * 8)
    whole = n_eighths // 8
    remainder = n_eighths % 8

    fraction_map = {
        1: '1/8',
        2: '1/4',
        3: '3/8',
        4: '1/2',
        5: '5/8',
        6: '3/4',
        7: '7/8',
    }

    if whole == 0 and remainder == 0:
        return '0'
    if remainder == 0:
        return str(whole)
    if whole == 0:
        return fraction_map[remainder]
    return f"{whole} {fraction_map[remainder]}"


def _scale_ingredient_line(text, factor):
    """Scale the leading quantity in an ingredient line by a factor."""
    qty, rest = _parse_quantity_and_rest(text)
    if qty is None:
        # No recognizable leading quantity; leave as-is.
        return text
    scaled = qty * factor
    return f"{_format_quantity(scaled)}{rest}"


def _dedupe_recipes_by_url(recipes):
    """
    Remove duplicate recipes that have the same URL.

    - Keeps the first occurrence of each URL (preserving current order).
    - Merges categories (union, preserving order and uniqueness).
    - If any duplicate is favorited, the kept recipe stays favorited.
    """
    seen = {}
    deduped = []
    removed = 0

    for recipe in recipes:
        url = recipe.get('url')

        # If URL is missing, treat this recipe as unique.
        if not url:
            deduped.append(recipe)
            continue

        if url not in seen:
            deduped.append(recipe)
            seen[url] = recipe
        else:
            existing = seen[url]

            # Merge favorite flag
            if recipe.get('favorite'):
                existing['favorite'] = True

            # Merge categories (ensure lists, then take union preserving order)
            existing_cats = existing.get('category') or []
            new_cats = recipe.get('category') or []
            if isinstance(existing_cats, str):
                existing_cats = [existing_cats]
            if isinstance(new_cats, str):
                new_cats = [new_cats]
            merged = list(dict.fromkeys(existing_cats + new_cats))
            existing['category'] = merged

            removed += 1

    return deduped, removed


@app.route('/recipe/<int:recipe_id>/cooked', methods=['POST'])
def mark_recipe_cooked(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if not recipe:
        flash('Recipe not found.')
        return redirect(url_for('index'))

    # Increment cooked count
    try:
        current_count = int(recipe.get('cooked_count') or 0)
    except (TypeError, ValueError):
        current_count = 0
    recipe['cooked_count'] = current_count + 1

    # Update last cooked date (today)
    recipe['last_cooked'] = date.today().isoformat()

    # Update "made again?" preference
    made_again = bool(request.form.get('made_again'))
    recipe['made_again'] = made_again

    save_recipes(recipes)

    servings_param = request.form.get('servings')
    if servings_param:
        try:
            return redirect(url_for('view_recipe', recipe_id=recipe_id, servings=int(servings_param)))
        except ValueError:
            pass
    return redirect(url_for('view_recipe', recipe_id=recipe_id))


@app.route('/recipe/<int:recipe_id>/meta', methods=['POST'])
def update_recipe_meta(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if not recipe:
        flash('Recipe not found.')
        return redirect(url_for('index'))

    notes = request.form.get('notes', '').strip()
    tags = request.form.getlist('tags')
    rating_raw = request.form.get('rating')
    servings_param = request.form.get('servings')

    rating = None
    if rating_raw:
        try:
            rating_val = int(rating_raw)
            if 1 <= rating_val <= 5:
                rating = rating_val
        except ValueError:
            rating = None

    recipe['notes'] = notes
    recipe['tags'] = tags
    if rating is None:
        recipe.pop('rating', None)
    else:
        recipe['rating'] = rating

    save_recipes(recipes)

    if servings_param:
        try:
            return redirect(url_for('view_recipe', recipe_id=recipe_id, servings=int(servings_param)))
        except ValueError:
            pass
    return redirect(url_for('view_recipe', recipe_id=recipe_id))


@app.route('/recipe/<int:recipe_id>')
def view_recipe(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if not recipe:
        return 'Recipe not found', 404

    base_servings = recipe.get('servings') or 4
    try:
        target_servings = int(request.args.get('servings', base_servings))
    except (TypeError, ValueError):
        target_servings = base_servings

    if target_servings <= 0:
        target_servings = base_servings

    factor = float(target_servings) / float(base_servings) if base_servings else 1.0

    scaled_ingredients = [
        _scale_ingredient_line(ing, factor) for ing in recipe.get('ingredients', [])
    ]

    return render_template(
        'recipe.html',
        recipe=recipe,
        ingredients=scaled_ingredients,
        base_servings=base_servings,
        current_servings=target_servings,
        all_tags=TAGS,
    )


@app.route('/dedupe_recipes', methods=['POST'])
def dedupe_recipes():
    recipes = load_recipes()
    if not recipes:
        flash('No recipes to deduplicate.')
        return redirect(url_for('index'))

    deduped, removed = _dedupe_recipes_by_url(recipes)
    if removed:
        save_recipes(deduped)
        flash(f'Removed {removed} duplicate recipe(s) by URL.')
    else:
        flash('No duplicate recipes found.')

    return redirect(url_for('index'))


@app.route('/reset_cooked', methods=['POST'])
def reset_cooked():
    recipes = load_recipes()
    if not recipes:
        flash('No recipes to reset.')
        return redirect(url_for('index'))

    updated = 0
    for recipe in recipes:
        if recipe.get('cooked_count') or recipe.get('last_cooked') or recipe.get('made_again'):
            recipe['cooked_count'] = 0
            recipe['last_cooked'] = None
            recipe['made_again'] = False
            updated += 1

    save_recipes(recipes)
    flash(f'Reset cooked counters for {updated} recipe(s).')
    return redirect(url_for('index'))

@app.route('/recipe/<int:recipe_id>/categories_json')
def get_recipe_categories_json(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if recipe:
        return jsonify(recipe['category'])
    return jsonify({'error': 'Recipe not found'}), 404

@app.route('/recipe/<int:recipe_id>/delete', methods=['POST'])
def delete_recipe(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if recipe and recipe.get('favorite'):
        flash('This recipe is favorited. Unfavorite it before deleting.')
        return redirect(url_for('index'))

    recipes = [r for r in recipes if r['id'] != recipe_id]
    save_recipes(recipes)
    return redirect(url_for('index'))

@app.route('/recipe/<int:recipe_id>/edit', methods=['POST'])
def edit_recipe(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if recipe:
        recipe['title'] = request.form.get('title', recipe['title'])
        recipe['category'] = request.form.getlist('category')
        save_recipes(recipes)
    return redirect(url_for('index'))

@app.route('/recipe/<int:recipe_id>/toggle_favorite', methods=['POST'])
def toggle_favorite(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if recipe:
        recipe['favorite'] = not recipe.get('favorite', False)
        save_recipes(recipes)
    return redirect(url_for('index'))
    
@app.route('/update_order', methods=['POST'])
def update_order():
    data = request.get_json()
    new_order = data.get('order')
    if not new_order:
        return jsonify({'success': False, 'message': 'New order not provided.'}), 400

    recipes = load_recipes()
    ordered_recipes = []
    recipe_map = {r['id']: r for r in recipes}

    for recipe_id in new_order:
        if int(recipe_id) in recipe_map:
            ordered_recipes.append(recipe_map[int(recipe_id)])
    
    save_recipes(ordered_recipes)
    return jsonify({'success': True, 'message': 'Recipe order updated.'})


@app.route('/meal_plan/set_day', methods=['POST'])
def set_meal_plan_day():
    day = request.form.get('day')
    recipe_id_raw = request.form.get('recipe_id')

    if not day or day not in DAYS_OF_WEEK or not recipe_id_raw:
        flash('Please select a day to add this recipe to the meal plan.')
        return redirect(url_for('index'))

    try:
        recipe_id = int(recipe_id_raw)
    except ValueError:
        flash('Invalid recipe selected.')
        return redirect(url_for('index'))

    recipes = load_recipes()
    recipe_map = {r['id']: r for r in recipes}
    if recipe_id not in recipe_map:
        flash('Recipe not found.')
        return redirect(url_for('index'))

    plan = load_meal_plan() or {}
    plan[day] = recipe_id
    save_meal_plan(plan)

    title = recipe_map[recipe_id]['title']
    flash(f'Added "{title}" to {day}.')
    return redirect(url_for('index'))


@app.route('/meal_plan/clear_day', methods=['POST'])
def clear_meal_plan_day():
    day = request.form.get('day')
    if not day or day not in DAYS_OF_WEEK:
        flash('Invalid day.')
        return redirect(url_for('index'))

    plan = load_meal_plan() or {}
    had_value = bool(plan.get(day))
    plan[day] = None
    save_meal_plan(plan)

    if had_value:
        flash(f'Removed meal for {day}.')
    else:
        flash(f'No meal set for {day}.')

    return redirect(url_for('index'))


@app.route('/meal_plan', methods=['GET', 'POST'])
def meal_plan():
    recipes = load_recipes()
    plan = load_meal_plan() or {}
    recipe_map = {r['id']: r for r in recipes}

    if request.method == 'POST':
        new_plan = {}
        for day in DAYS_OF_WEEK:
            value = request.form.get(day)
            if not value or value == 'none':
                new_plan[day] = None
            else:
                try:
                    rid = int(value)
                except ValueError:
                    new_plan[day] = None
                else:
                    new_plan[day] = rid if rid in recipe_map else None

        save_meal_plan(new_plan)
        flash('Meal plan updated.')
        return redirect(url_for('meal_plan'))

    # Ensure all days are present
    for day in DAYS_OF_WEEK:
        plan.setdefault(day, None)

    return render_template('meal_plan.html', recipes=recipes, plan=plan, days=DAYS_OF_WEEK)


@app.route('/shopping_list')
def shopping_list():
    recipes = load_recipes()
    plan = load_meal_plan() or {}
    recipe_map = {r['id']: r for r in recipes}

    ingredient_counts = {}

    for day, rid in plan.items():
        if not rid:
            continue
        recipe = recipe_map.get(rid)
        if not recipe:
            continue
        for ing in recipe.get('ingredients', []):
            ingredient_counts[ing] = ingredient_counts.get(ing, 0) + 1

    # Convert to a list of (ingredient, count) pairs for display
    items = sorted(ingredient_counts.items(), key=lambda x: x[0].lower())

    return render_template('shopping_list.html', items=items, plan=plan, days=DAYS_OF_WEEK)


if __name__ == '__main__':
    app.run(debug=True)
