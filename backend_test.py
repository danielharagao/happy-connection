def _crm_request_with_retry(req, timeout=5, max_attempts=3, backoff_factor=0.5):
    import time
    from urllib.request import urlopen
    from urllib.error import HTTPError, URLError
    
    last_exc = None
    for attempt in range(max_attempts):
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                return body, int(getattr(resp, "status", 200)), resp.headers
        except HTTPError as exc:
            # Maybe retry on 5xx
            code = getattr(exc, "code", 500)
            if code < 500:
                raise exc # Don't retry 4xx
            last_exc = exc
        except URLError as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc
        
        if attempt < max_attempts - 1:
            time.sleep(backoff_factor * (2 ** attempt))
            
    raise last_exc
