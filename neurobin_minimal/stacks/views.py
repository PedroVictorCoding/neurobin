from django.views.generic import TemplateView
from .models import Stack


class MyStacksView(TemplateView):
    template_name = 'stacks/my_stacks.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['stacks'] = Stack.objects.all()
        return ctx
