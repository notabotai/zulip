from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token

from zerver.lib.response import json_success
from zerver.lib.typed_endpoint import typed_endpoint
from zerver.models import UserProfile


@typed_endpoint
def get_nb_csrf_token(request: HttpRequest, user_profile: UserProfile) -> HttpResponse:
    return json_success(request, {"csrf_token": get_token(request)})
