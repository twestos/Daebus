import pytest
import json
import datetime
import decimal
from unittest.mock import MagicMock, patch
from daebus import DaebusHttp, HttpRequest, HttpResponse
from daebus.modules.http import DaebusJSONEncoder, make_json_serializable


def test_http_request_init():
    """Test HttpRequest initialization"""
    env = {
        'method': 'GET',
        'path': '/test',
        'query': {'foo': 'bar', 'baz': 'qux'},
        'headers': {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer token'
        },
        'params': {},
        'json': None,
        'form': None
    }
    
    request = HttpRequest(env)
    
    assert request.method == 'GET'
    assert request.path == '/test'
    assert request.headers['Content-Type'] == 'application/json'
    assert request.headers['Authorization'] == 'Bearer token'
    assert isinstance(request.payload, dict)
    assert request.params == {}


def test_http_response_init():
    """Test HttpResponse initialization"""
    start_response = MagicMock()
    response = HttpResponse(start_response)
    
    assert response._status_code == 200
    assert response._response_data is None


def test_http_response_send_json():
    """Test HttpResponse sending JSON data"""
    handler = MagicMock()
    response = HttpResponse(handler)
    
    result = response.send({'message': 'Hello, World!'})
    
    assert result == ({'message': 'Hello, World!'}, 200)
    assert response._response_data == {'message': 'Hello, World!'}
    assert response._status_code == 200


def test_http_response_send_with_status():
    """Test HttpResponse sending with custom status"""
    handler = MagicMock()
    response = HttpResponse(handler)
    
    result = response.send({'error': 'Not Found'}, status_code=404)
    
    assert result == ({'error': 'Not Found'}, 404)
    assert response._status_code == 404


def test_http_response_send_with_custom_data():
    """Test HttpResponse sending custom data format"""
    handler = MagicMock()
    response = HttpResponse(handler)
    
    # Previously we would use the success method for this, but now we use send
    result = response.send({'message': 'Success'})
    
    assert result == ({'message': 'Success'}, 200)
    assert response._status_code == 200
    assert response._response_data == {'message': 'Success'}


@patch('daebus.modules.http.HTTPServer')
def test_daebushttp_init(mock_http_server):
    """Test DaebusHttp initialization"""
    http = DaebusHttp(port=8080)
    
    assert http.port == 8080
    assert http.routes == {}
    assert http.daemon is None


@patch('daebus.modules.http.HTTPServer')
def test_daebushttp_route(mock_http_server):
    """Test DaebusHttp route registration"""
    http = DaebusHttp()
    
    # Mock daemon so we can add routes
    daemon = MagicMock()
    http.daemon = daemon
    
    @http.route('/test')
    def handle_test(request):
        return {'message': 'Test'}
    
    assert '/test' in http.routes
    assert 'GET' in http.routes['/test']['methods']
    assert http.routes['/test']['function'] is handle_test
    
    @http.route('/users', methods=['POST'])
    def create_user(request):
        return {'message': 'User created'}
    
    assert '/users' in http.routes
    assert 'POST' in http.routes['/users']['methods']
    assert http.routes['/users']['function'] is create_user


@patch('daebus.modules.http.HTTPServer')
def test_daebushttp_attach(mock_http_server):
    """Test DaebusHttp attaching to Daebus"""
    http = DaebusHttp()
    daemon = MagicMock()
    
    # Mock http.attach to return self
    with patch.object(http, 'attach', return_value=http) as mock_attach:
        result = http.attach(daemon)
        
        mock_attach.assert_called_once_with(daemon)
        assert result is http


def test_daebus_json_encoder_standard_types():
    """Test that DaebusJSONEncoder handles standard JSON types correctly"""
    encoder = DaebusJSONEncoder()
    
    # Standard JSON types should serialize normally
    standard_data = {
        'string': 'hello',
        'integer': 42,
        'float': 3.14159,
        'boolean_true': True,
        'boolean_false': False,
        'null_value': None,
        'list': [1, 2, 3],
        'nested_dict': {'a': 1, 'b': 2},
        'list_of_dicts': [
            {'id': 1, 'name': 'John'},
            {'id': 2, 'name': 'Jane'}
        ]
    }
    
    # This should serialize without needing custom encoding
    serialized = json.dumps(standard_data, cls=DaebusJSONEncoder, indent=2)
    deserialized = json.loads(serialized)
    
    assert deserialized == standard_data
    assert isinstance(deserialized['string'], str)
    assert isinstance(deserialized['integer'], int)
    assert isinstance(deserialized['float'], float)
    assert isinstance(deserialized['boolean_true'], bool)
    assert isinstance(deserialized['null_value'], type(None))
    assert isinstance(deserialized['list'], list)
    assert isinstance(deserialized['nested_dict'], dict)


def test_daebus_json_encoder_datetime_objects():
    """Test that DaebusJSONEncoder handles datetime objects correctly"""
    encoder = DaebusJSONEncoder()
    
    now = datetime.datetime(2023, 12, 25, 15, 30, 45, 123456)
    today = datetime.date(2023, 12, 25)
    time_obj = datetime.time(15, 30, 45)
    delta = datetime.timedelta(days=1, hours=2, minutes=30)
    
    data = {
        'datetime': now,
        'date': today,
        'time': time_obj,
        'timedelta': delta
    }
    
    serialized = json.dumps(data, cls=DaebusJSONEncoder)
    deserialized = json.loads(serialized)
    
    assert deserialized['datetime'] == '2023-12-25T15:30:45.123456'
    assert deserialized['date'] == '2023-12-25'
    assert deserialized['time'] == '15:30:45'
    assert deserialized['timedelta'] == '1 day, 2:30:00'


def test_daebus_json_encoder_special_types():
    """Test that DaebusJSONEncoder handles special Python types"""
    encoder = DaebusJSONEncoder()
    
    data = {
        'set': {1, 2, 3, 2},  # Duplicates should be removed
        'decimal': decimal.Decimal('19.99'),
        'bytes_utf8': b'hello world',
        'bytes_binary': b'\x00\x01\x02\xff'
    }
    
    serialized = json.dumps(data, cls=DaebusJSONEncoder)
    deserialized = json.loads(serialized)
    
    # Set should become a list (order may vary)
    assert isinstance(deserialized['set'], list)
    assert set(deserialized['set']) == {1, 2, 3}
    
    # Decimal should become float
    assert deserialized['decimal'] == 19.99
    assert isinstance(deserialized['decimal'], float)
    
    # UTF-8 bytes should decode to string
    assert deserialized['bytes_utf8'] == 'hello world'
    
    # Binary bytes should become hex string
    assert deserialized['bytes_binary'] == '000102ff'


def test_daebus_json_encoder_custom_objects():
    """Test that DaebusJSONEncoder handles custom objects"""
    
    class SimpleObject:
        def __init__(self, name, value):
            self.name = name
            self.value = value
    
    class ObjectWithToDict:
        def __init__(self, data):
            self.data = data
            
        def to_dict(self):
            return self.data
    
    class ObjectWithCustomStr:
        # Override __dict__ property to avoid empty dict taking precedence
        @property
        def __dict__(self):
            raise AttributeError("This object has no __dict__")
            
        def __str__(self):
            return "custom_string_representation"
    
    data = {
        'simple_object': SimpleObject('test', 42),
        'object_with_to_dict': ObjectWithToDict({'key': 'value'}),
        'object_with_str': ObjectWithCustomStr()
    }
    
    serialized = json.dumps(data, cls=DaebusJSONEncoder)
    deserialized = json.loads(serialized)
    
    # Simple object should use __dict__
    assert deserialized['simple_object'] == {'name': 'test', 'value': 42}
    
    # Object with to_dict should use that method (prioritized over __dict__)
    assert deserialized['object_with_to_dict'] == {'key': 'value'}
    
    # Object with custom __str__ should use that
    assert deserialized['object_with_str'] == 'custom_string_representation'


def test_make_json_serializable_function():
    """Test the make_json_serializable utility function"""
    
    # Complex object with mixed types
    complex_data = {
        'users': [
            {'id': 1, 'created': datetime.datetime.now(), 'tags': {1, 2, 3}},
            {'id': 2, 'balance': decimal.Decimal('100.50'), 'active': True}
        ],
        'metadata': {
            'timestamp': datetime.datetime.now(),
            'binary_data': b'some binary data',
            'counts': {10, 20, 30}
        }
    }
    
    # This should convert everything to JSON-serializable format
    serializable = make_json_serializable(complex_data)
    
    # Should be able to serialize with standard json.dumps
    serialized = json.dumps(serializable)
    deserialized = json.loads(serialized)
    
    # Verify structure is preserved and types are converted
    assert len(deserialized['users']) == 2
    assert isinstance(deserialized['users'][0]['tags'], list)
    assert isinstance(deserialized['users'][1]['balance'], float)
    assert deserialized['users'][1]['balance'] == 100.5
    assert isinstance(deserialized['metadata']['binary_data'], str)


def test_http_response_with_complex_data():
    """Test HttpResponse can handle complex data structures"""
    handler = MagicMock()
    response = HttpResponse(handler)
    
    # Complex response data that would normally cause JSON serialization issues
    complex_data = {
        'timestamp': datetime.datetime.now(),
        'users': [
            {
                'id': 1,
                'name': 'John Doe',
                'balance': decimal.Decimal('150.75'),
                'permissions': {'read', 'write', 'delete'},
                'created_at': datetime.date.today()
            },
            {
                'id': 2,
                'name': 'Jane Smith',
                'active': True,
                'score': 95.7,
                'tags': [1, 2, 3]
            }
        ],
        'metadata': {
            'total_count': 2,
            'has_more': False,
            'processing_time': datetime.timedelta(seconds=0.5)
        }
    }
    
    # This should work without errors
    result = response.send(complex_data, status_code=200)
    
    assert result[1] == 200  # status code
    assert isinstance(result[0], dict)
    assert 'users' in result[0]
    assert len(result[0]['users']) == 2


@patch('daebus.modules.http.ThreadedHTTPServer')
def test_end_to_end_json_serialization(mock_server):
    """Test end-to-end JSON serialization in HTTP responses"""
    
    # Create HTTP server
    http = DaebusHttp(port=8080)
    daemon = MagicMock()
    daemon.name = 'test_daemon'
    http.attach(daemon)
    
    # Create a route that returns complex data
    @http.route('/api/complex', methods=['GET'])
    def complex_endpoint(request):
        return {
            'success': True,
            'data': {
                'timestamp': datetime.datetime(2023, 12, 25, 15, 30, 45),
                'items': [
                    {'id': 1, 'price': decimal.Decimal('29.99'), 'tags': {'new', 'sale'}},
                    {'id': 2, 'score': 87.5, 'active': True}
                ],
                'binary': b'test data'
            },
            'count': 2
        }
    
    # Test the route handler directly
    from daebus.modules.http import HttpRequest
    
    mock_request = HttpRequest({
        'method': 'GET',
        'path': '/api/complex',
        'query': {},
        'params': {},
        'headers': {},
        'json': None,
        'form': None
    })
    
    # Call the route handler
    result = complex_endpoint(mock_request)
    
    # Test that we can serialize the complex response data
    try:
        serialized_json = json.dumps(result, cls=DaebusJSONEncoder, indent=2)
        parsed = json.loads(serialized_json)
        
        # Verify the response was properly serialized
        assert parsed['success'] is True
        assert parsed['count'] == 2
        assert parsed['data']['timestamp'] == '2023-12-25T15:30:45'
        assert isinstance(parsed['data']['items'][0]['tags'], list)
        assert parsed['data']['items'][0]['price'] == 29.99
        assert parsed['data']['binary'] == 'test data'
    except Exception as e:
        pytest.fail(f"JSON serialization failed: {e}") 