from database import DatabaseManager
from core import Crossposter

if __name__ == "__main__":
    db_manager = DatabaseManager()
    app = Crossposter(db_manager)
    app.run()
