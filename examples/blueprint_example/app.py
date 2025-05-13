from daebus import Daebus, DaebusHttp
from .routes import api, pubsub, tasks

def create_app():
    # Create the Daebus application
    app = Daebus('blueprint_example')
    
    # Attach the HTTP component
    http = app.attach(DaebusHttp(port=8080))
    
    # Register blueprints
    app.register_blueprint(api)
    app.register_blueprint(pubsub)
    app.register_blueprint(tasks)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run('blueprint_example_service') 