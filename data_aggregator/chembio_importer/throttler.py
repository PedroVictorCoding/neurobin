"""
API rate limiting and request throttling utilities
"""
import time
import logging
from functools import wraps
from typing import Callable, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import SLOW_MODE, SLEEP_INTERVAL, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)


class RateLimitedSession:
    """HTTP session with built-in rate limiting and retry logic"""
    
    def __init__(self, sleep_interval: float = SLEEP_INTERVAL, max_retries: int = MAX_RETRIES):
        self.sleep_interval = sleep_interval
        self.max_retries = max_retries
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set reasonable timeout
        self.session.timeout = 30
        
        # Track last request time for rate limiting
        self.last_request_time = 0
    
    def _wait_if_needed(self):
        """Wait if necessary to respect rate limits"""
        if SLOW_MODE:
            time_since_last = time.time() - self.last_request_time
            if time_since_last < self.sleep_interval:
                sleep_time = self.sleep_interval - time_since_last
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
    
    def get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET request"""
        self._wait_if_needed()
        self.last_request_time = time.time()
        
        logger.debug(f"Making GET request to: {url}")
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response
    
    def post(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited POST request"""
        self._wait_if_needed()
        self.last_request_time = time.time()
        
        logger.debug(f"Making POST request to: {url}")
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response


def rate_limited(sleep_interval: float = SLEEP_INTERVAL):
    """
    Decorator to add rate limiting to any function
    """
    def decorator(func: Callable) -> Callable:
        last_call_time = 0
        
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            nonlocal last_call_time
            
            if SLOW_MODE:
                time_since_last = time.time() - last_call_time
                if time_since_last < sleep_interval:
                    sleep_time = sleep_interval - time_since_last
                    logger.debug(f"Rate limiting {func.__name__}: sleeping for {sleep_time:.2f} seconds")
                    time.sleep(sleep_time)
            
            last_call_time = time.time()
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def retry_on_failure(max_attempts: int = MAX_RETRIES, delay: float = RETRY_DELAY,
                    exceptions: tuple = (requests.RequestException, ConnectionError)):
    """
    Decorator to retry function calls on specified exceptions
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}")
                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
                        raise last_exception
            
            raise last_exception
        
        return wrapper
    return decorator


class APIThrottler:
    """Advanced API throttling with per-endpoint rate limits"""
    
    def __init__(self):
        self.endpoint_timers = {}
        self.global_timer = 0
    
    def wait_for_endpoint(self, endpoint: str, rate_limit: float = SLEEP_INTERVAL):
        """Wait if necessary for a specific endpoint"""
        current_time = time.time()
        
        if endpoint in self.endpoint_timers:
            time_since_last = current_time - self.endpoint_timers[endpoint]
            if time_since_last < rate_limit:
                sleep_time = rate_limit - time_since_last
                logger.debug(f"Endpoint throttling for {endpoint}: sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
        
        self.endpoint_timers[endpoint] = time.time()
    
    def wait_global(self, rate_limit: float = SLEEP_INTERVAL):
        """Global rate limiting across all endpoints"""
        if SLOW_MODE:
            current_time = time.time()
            time_since_last = current_time - self.global_timer
            
            if time_since_last < rate_limit:
                sleep_time = rate_limit - time_since_last
                logger.debug(f"Global throttling: sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
            
            self.global_timer = time.time()


# Global instances
rate_limited_session = RateLimitedSession()
api_throttler = APIThrottler()


def make_throttled_request(url: str, method: str = 'GET', endpoint_name: str = None,
                          rate_limit: float = SLEEP_INTERVAL, **kwargs) -> requests.Response:
    """
    Make a throttled HTTP request with automatic retry and rate limiting
    """
    if endpoint_name:
        api_throttler.wait_for_endpoint(endpoint_name, rate_limit)
    else:
        api_throttler.wait_global(rate_limit)
    
    @retry_on_failure()
    def _make_request():
        if method.upper() == 'GET':
            return rate_limited_session.get(url, **kwargs)
        elif method.upper() == 'POST':
            return rate_limited_session.post(url, **kwargs)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
    
    return _make_request()
