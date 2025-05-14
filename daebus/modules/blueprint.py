import logging
from typing import Dict, List, Optional, Callable, Any

class Blueprint:
    """
    A Blueprint is a way to organize a group of related routes and other
    functionality that can be registered on a Daebus app.
    
    Similar to Flask's Blueprint, this allows for modular application components
    that can be registered with the main application.
    
    Example:
        # In routes.py
        from daebus.modules.blueprint import Blueprint
        
        main = Blueprint('main')
        
        @main.action('hello')
        def hello_action():
            # action handler
            pass
            
        @main.route('/api/hello')
        def hello_route(req):
            return {"message": "Hello, world!"}
            
        # In app.py
        from daebus import Daebus
        from daebus.modules.http import DaebusHttp
        from .routes import main
        
        app = Daebus('my_app')
        http = app.attach(DaebusHttp(port=8080))
        
        # Register the blueprint
        app.register_blueprint(main)
    """
    
    def __init__(self, name: str):
        self.name = name
        self.action_handlers = {}
        self.routes = {}
        self.listen_handlers = {}
        self.socket_handlers = {}
        self.background_tasks = []
        self.thread_tasks = {}
        self.on_start_handlers = []
        self.logger = logging.getLogger(f"blueprint.{name}")
    
    def action(self, action_name: str):
        """Register an action handler within this blueprint"""
        def decorator(func):
            self.action_handlers[action_name] = func
            return func
        return decorator
    
    def route(self, path: str, methods: Optional[List[str]] = None):
        """Register an HTTP route handler within this blueprint"""
        if methods is None:
            methods = ['GET']
            
        def decorator(func):
            self.routes[path] = {
                'function': func,
                'methods': methods
            }
            return func
        return decorator
    
    def listen(self, channel: str):
        """Register a pubsub channel listener within this blueprint"""
        def decorator(func):
            self.listen_handlers[channel] = func
            return func
        return decorator
    
    def socket(self, message_type: str):
        """
        Register a WebSocket message handler within this blueprint.
        
        Args:
            message_type: The type of message to handle
            
        Example:
            @blueprint.socket("chat_message")
            def handle_chat_message(req, sid):
                # req is the raw message data
                # sid is the client ID (session ID)
                
                message = req.get('message', '')
                print(f"Got message from {sid}: {message}")
                
                # Return a response (will be sent automatically)
                return {"status": "received"}
        """
        def decorator(func):
            self.socket_handlers[message_type] = func
            return func
        return decorator
    
    def socket_connect(self):
        """
        Register a handler for WebSocket connect events.
        
        This is a shorthand for @blueprint.socket('connect')
        
        Example:
            @blueprint.socket_connect()
            def on_connect(req, sid):
                print(f"Client {sid} connected")
                return {"status": "connected"}
        """
        return self.socket('connect')
    
    def socket_disconnect(self):
        """
        Register a handler for WebSocket disconnect events.
        
        This is a shorthand for @blueprint.socket('disconnect')
        
        Example:
            @blueprint.socket_disconnect()
            def on_disconnect(req, sid):
                print(f"Client {sid} disconnected")
        """
        return self.socket('disconnect')
    
    def socket_register(self):
        """
        Register a handler for WebSocket client registration events.
        
        This is a shorthand for @blueprint.socket('register')
        
        Example:
            @blueprint.socket_register()
            def on_register(req, sid):
                user_data = req.get('user_data', {})
                print(f"Client {sid} registered with data: {user_data}")
                return {"status": "registered", "client_id": sid}
        """
        return self.socket('register')
    
    def background(self, name: str, interval: int):
        """Register a background task within this blueprint"""
        def decorator(func):
            self.background_tasks.append((name, interval, func))
            return func
        return decorator
        
    def thread(self, name: str, auto_start: bool = True):
        """Register a thread task within this blueprint"""
        def decorator(func):
            self.thread_tasks[name] = {
                "func": func,
                "auto_start": auto_start
            }
            return func
        return decorator
    
    def on_start(self):
        """Register an on_start handler within this blueprint"""
        def decorator(func):
            self.on_start_handlers.append(func)
            return func
        return decorator 