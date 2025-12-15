from flask import Flask, render_template, request, jsonify, redirect, url_for
from web_scraper import scrape_recipe_data
from database import load_recipes, save_recipes

app = Flask(__name__)

@app.route('/')
def index():
    recipes = load_recipes()
    categories = sorted(["Breakfast", "Lunch", "Dinner", "Beef", "Chicken", "Fish", "Desserts", "Vegetarian", "Pasta", "Soups", "Other", "Appetizer", "Salad", "Side Dish", "Vegan", "Gluten-Free", "Mexican", "Italian", "Indian", "Chinese", "Japanese"])
    return render_template('index.html', recipes=recipes, categories=categories)

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
        'category': categories,
        'ingredients': scraped_data['ingredients'],
        'instructions': scraped_data['instructions'],
        'url': scraped_data['url']
    }
    
    recipes.insert(0, new_recipe)
    save_recipes(recipes)
    
    return redirect(url_for('index'))

@app.route('/recipe/<int:recipe_id>')
def view_recipe(recipe_id):
    recipes = load_recipes()
    recipe = next((r for r in recipes if r['id'] == recipe_id), None)
    if recipe:
        return render_template('recipe.html', recipe=recipe)
    return 'Recipe not found', 404

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


if __name__ == '__main__':
    app.run(debug=True)
