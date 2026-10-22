from django.urls import path

from .telecalling_views import telecalling_analytics, telecalling_call_log, telecalling_call_recording, telecalling_queue

urlpatterns = [
    path("telecalling/queue", telecalling_queue, name="telecalling-queue"),
    path("telecalling/calls/log", telecalling_call_log, name="telecalling-call-log"),
    path("telecalling/calls/<int:call_id>/recording/", telecalling_call_recording, name="telecalling-call-recording"),
    path("telecalling/analytics", telecalling_analytics, name="telecalling-analytics"),
]
