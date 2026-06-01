"""Shared admin mixins for Roma ERP."""
from django.shortcuts import redirect


class StayOnPageMixin:
    """After a plain Save, stay on the change page instead of going to the list."""

    def response_post_save_change(self, request, obj):
        return redirect(request.path)

    def response_post_save_add(self, request, obj):
        # Go to the change page of the newly-added object (so inlines show).
        from django.urls import reverse
        info = (self.model._meta.app_label, self.model._meta.model_name)
        return redirect(reverse('admin:%s_%s_change' % info, args=[obj.pk]))


class LockAfterPostMixin:
    """Make all fields + inlines read-only once a record is posted/locked, so
    quantities / products / prices can't change after the GL entry was booked.

    Configure with:
      lock_field   = 'status'   (or 'is_posted')
      lock_values  = ('POSTED', 'RELEASED', 'COMPLETED', 'CANCELLED')
      unlock_always = ('notes',)   # fields that stay editable even when locked
    """
    lock_field = 'status'
    lock_values = ('POSTED', 'RELEASED', 'COMPLETED', 'CANCELLED')
    unlock_always = ()

    def _is_locked(self, obj):
        if obj is None:
            return False
        val = getattr(obj, self.lock_field, None)
        if isinstance(val, bool):          # e.g. is_posted
            return val
        return val in self.lock_values

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if self._is_locked(obj):
            for f in self.model._meta.fields:
                if f.name not in self.unlock_always and f.name not in ro:
                    ro.append(f.name)
        return ro

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        if self._is_locked(obj):
            for inline in instances:
                inline._roma_locked = True
        return instances

    def has_delete_permission(self, request, obj=None):
        if self._is_locked(obj):
            return False
        return super().has_delete_permission(request, obj)


class LockedInlineMixin:
    """Mixin for inlines that should become read-only when the parent is locked.
    The parent admin sets `_roma_locked` on the inline instance."""

    def _locked(self):
        return getattr(self, '_roma_locked', False)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if self._locked():
            field_names = [f.name for f in self.model._meta.fields
                           if f.name not in ('id',)]
            for f in field_names:
                if f not in ro:
                    ro.append(f)
        return ro

    def has_add_permission(self, request, obj=None):
        if self._locked():
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._locked():
            return False
        return super().has_delete_permission(request, obj)
