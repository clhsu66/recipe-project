# web_scraper.py

# Import the necessary libraries
import requests
from bs4 import BeautifulSoup
import json

def scrape_recipe_data(url):
    """
    Scrapes recipe data from a given URL.

    Args:
        url (str): The URL of the recipe page.

    Returns:
        dict: A dictionary containing the recipe's title, ingredients, 
              instructions, and URL, or None if scraping fails.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        html_content = response.text
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching the page: {e}")
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    json_scripts = soup.find_all('script', type='application/ld+json')

    recipe_data = None
    for script in json_scripts:
        data = json.loads(script.string)
        if isinstance(data, list) and data:
            # For this specific site, the recipe can be in a '@graph' list
            graph_data = data[0] if '@graph' not in data[0] else next((item for item in data[0]['@graph'] if item.get('@type') == 'Recipe'), None)

            if graph_data:
                 if isinstance(graph_data.get('@type'), list) and 'Recipe' in graph_data.get('@type'):
                    recipe_data = graph_data
                    break
                 elif graph_data.get('@type') == 'Recipe':
                    recipe_data = graph_data
                    break
    
    if not recipe_data:
        # Fallback for other structures
        for script in json_scripts:
            data = json.loads(script.string)
            if isinstance(data, list):
                recipe_data = next((item for item in data if item.get('@type') and ('Recipe' in item.get('@type') or 'recipe' in item.get('@type'))), None)
                if recipe_data:
                    break
            elif isinstance(data, dict) and data.get('@type') and ('Recipe' in data.get('@type') or 'recipe' in data.get('@type')):
                recipe_data = data
                break


    if recipe_data:
        title = recipe_data.get('name', 'No Title Found')
        ingredients = recipe_data.get('recipeIngredient', [])
        instructions_list = recipe_data.get('recipeInstructions', [])
        
        instructions = []
        for step in instructions_list:
            if isinstance(step, dict) and step.get('@type') == 'HowToStep':
                instructions.append(step.get('text', ''))
            elif isinstance(step, str):
                instructions.append(step)

        return {
            'title': title,
            'ingredients': ingredients,
            'instructions': instructions,
            'url': url
        }
    
    return None