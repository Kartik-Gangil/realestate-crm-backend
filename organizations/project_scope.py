from contextvars import ContextVar

from django.db import models


_current_project_id = ContextVar("current_project_id", default=None)


def get_current_project_id():
    return _current_project_id.get()


def set_current_project(project_id):
    return _current_project_id.set(project_id)


def reset_current_project(token):
    _current_project_id.reset(token)


class ProjectScopedQuerySet(models.QuerySet):
    def _with_current_project(self, values):
        if values.get("project") is None and values.get("project_id") is None:
            project_id = get_current_project_id()
            if project_id is not None:
                values["project_id"] = project_id
        return values

    def create(self, **kwargs):
        return super().create(**self._with_current_project(kwargs))


class ProjectScopedManager(models.Manager.from_queryset(ProjectScopedQuerySet)):
    def get_queryset(self):
        queryset = super().get_queryset()
        project_id = get_current_project_id()
        return queryset.filter(project_id=project_id) if project_id is not None else queryset
