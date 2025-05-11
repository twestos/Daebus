import pytest
from unittest.mock import MagicMock, patch
from daebus import DaebusHttp, HttpRequest, HttpResponse


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


def test_http_response_send_with_success():
    """Test HttpResponse sending with success method"""
    handler = MagicMock()
    response = HttpResponse(handler)
    
    result = response.success({'message': 'Success'})
    
    assert result == ({'message': 'Success'}, 200)
    assert response._status_code == 200


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