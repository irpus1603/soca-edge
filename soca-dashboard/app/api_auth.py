import functools
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import EdgeConfig


def require_api_key(view_func):
    """Decorator: validates Authorization: Api-Key <token> header. Implies csrf_exempt."""
    @csrf_exempt
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Api-Key '):
            return JsonResponse({'error': 'Invalid or missing API key'}, status=403)
        token = auth[len('Api-Key '):]
        edge = EdgeConfig.objects.first()
        if not edge or not edge.api_key or token != edge.api_key:
            return JsonResponse({'error': 'Invalid or missing API key'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper
