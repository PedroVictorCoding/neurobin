from django.contrib.auth.mixins import LoginRequiredMixin

from django.views.generic import TemplateView
from django.shortcuts import redirect
from .models import Stack

from .forms import StackForm
from .forms_add_compound import AddCompoundForm
from .models import StackItem


class MyStacksView(LoginRequiredMixin, TemplateView):
    template_name = 'stacks/my_stacks.html'


    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        # Main form for creating stacks
        context['form'] = StackForm()
        # Attach an AddCompoundForm to each stack
        for stack in context['stacks']:
            stack.add_form = AddCompoundForm()
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        if 'add_stack' in request.POST:
            form = StackForm(request.POST)
            if form.is_valid():
                stack = form.save(commit=False)
                stack.user = request.user
                stack.save()
                return redirect('my_stacks')
            context = self.get_context_data(**kwargs)
            context['form'] = form
            for stack in context['stacks']:
                stack.add_form = AddCompoundForm()
            return self.render_to_response(context)
        elif 'add_compound_to_stack' in request.POST:
            stack_id = request.POST.get('stack_id')
            stack = Stack.objects.filter(id=stack_id, user=request.user).first()
            if not stack:
                return redirect('my_stacks')
            form = AddCompoundForm(request.POST)
            if form.is_valid():
                item = form.save(commit=False)
                item.stack = stack
                item.save()
                return redirect('my_stacks')
            # Rebuild context with forms
            context = self.get_context_data(**kwargs)
            context['form'] = StackForm()
            for s in context['stacks']:
                s.add_form = form if s.id == stack.id else AddCompoundForm()
            return self.render_to_response(context)
        else:
            return redirect('my_stacks')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stacks'] = Stack.objects.filter(user=self.request.user).prefetch_related('items__compound')
        return context
