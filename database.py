import os
from pymongo import MongoClient, errors
from pymongo.server_api import ServerApi
import atexit

# --- Connection Setup ---
# We retrieve the connection string from an environment variable for security.
MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    print("Warning: MONGO_URI environment variable not set. Using local JSON file will not work if deployed.")
    client = None
else:
    try:
        # Create a new client and connect to the server
        client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
        # Send a ping to confirm a successful connection
        client.admin.command('ping')
        print("Successfully connected to MongoDB!")
    except errors.ConnectionFailure as e:
        print(f"Could not connect to MongoDB: {e}")
        client = None
    except errors.ConfigurationError as e:
        print(f"MongoDB configuration error: {e}")
        client = None
    except Exception as e:
        print(f"An unexpected error occurred with MongoDB connection: {e}")
        client = None

if client:
    db = client.recipe_box
    # We will use a single document within a collection to store the entire list of recipes.
    # This closely mimics the behavior of the original JSON file-based storage.
    recipe_collection = db.recipe_list
else:
    db = None
    recipe_collection = None

def load_recipes():
    """Loads all recipes from a single document in the database."""
    if recipe_collection is None:
        print("Database not connected. Cannot load recipes.")
        return []

    doc = recipe_collection.find_one({"_id": "all_recipes"})
    if doc and "recipes" in doc:
        recipes = doc["recipes"]
        # Ensure category is always a list for consistency in the app
        for recipe in recipes:
            if isinstance(recipe.get('category'), str):
                recipe['category'] = [recipe['category']]
        return recipes
    return []

def save_recipes(recipes):
    """Saves the entire list of recipes to a single document in the database."""
    if recipe_collection is None:
        print("Database not connected. Cannot save recipes.")
        return

    # The `upsert=True` option creates the document if it doesn't exist yet.
    recipe_collection.update_one(
        {"_id": "all_recipes"},
        {"$set": {"recipes": recipes}},
        upsert=True
    )


def load_meal_plan():
    """Load the weekly meal plan stored as a separate document."""
    if recipe_collection is None:
        print("Database not connected. Cannot load meal plan.")
        return {}

    doc = recipe_collection.find_one({"_id": "meal_plan"})
    if doc and "plan" in doc:
        return doc["plan"]
    return {}


def save_meal_plan(plan):
    """Save the weekly meal plan as a separate document."""
    if recipe_collection is None:
        print("Database not connected. Cannot save meal plan.")
        return

    recipe_collection.update_one(
        {"_id": "meal_plan"},
        {"$set": {"plan": plan}},
        upsert=True
    )

def close_db_connection():
    if client:
        client.close()
        print("MongoDB connection closed.")

# Register the function to close the connection when the app exits
atexit.register(close_db_connection)
