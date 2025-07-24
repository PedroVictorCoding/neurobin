from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import json

from compounds.models import Compound
from .models import ChangeRequest, ChangeRequestComment, AppliedChange
from .forms import CompoundChangeRequestForm, ChangeRequestCommentForm, ReviewChangeRequestForm


@login_required
def change_request_list(request):
    """List all change requests"""
    if request.user.is_staff:
        # Staff can see all requests
        change_requests = ChangeRequest.objects.all()
    else:
        # Regular users can only see their own requests
        change_requests = ChangeRequest.objects.filter(requested_by=request.user)
    
    context = {
        'change_requests': change_requests,
        'can_review': request.user.is_staff,
    }
    return render(request, 'change_requests/list.html', context)


@login_required
def change_request_detail(request, pk):
    """View details of a specific change request"""
    change_request = get_object_or_404(ChangeRequest, pk=pk)
    
    # Check permissions
    if not request.user.is_staff and change_request.requested_by != request.user:
        messages.error(request, "You don't have permission to view this change request.")
        return redirect('change_requests:list')
    
    # Handle comment form
    if request.method == 'POST' and 'add_comment' in request.POST:
        comment_form = ChangeRequestCommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.change_request = change_request
            comment.user = request.user
            comment.save()
            messages.success(request, "Comment added successfully.")
            return redirect('change_requests:detail', pk=pk)
    else:
        comment_form = ChangeRequestCommentForm()
    
    # Handle review form (staff only)
    review_form = None
    if request.user.is_staff and change_request.status == 'pending':
        if request.method == 'POST' and 'review_action' in request.POST:
            review_form = ReviewChangeRequestForm(request.POST)
            if review_form.is_valid():
                action = review_form.cleaned_data['action']
                review_notes = review_form.cleaned_data['review_notes']
                
                change_request.status = action
                change_request.reviewed_by = request.user
                change_request.reviewed_at = timezone.now()
                change_request.review_notes = review_notes
                change_request.save()
                
                messages.success(request, f"Change request {action} successfully.")
                
                # Auto-apply if approved
                if action == 'approved':
                    try:
                        change_request.apply_changes(request.user)
                        messages.success(request, "Changes have been applied to the compound.")
                    except Exception as e:
                        messages.error(request, f"Error applying changes: {str(e)}")
                
                return redirect('change_requests:detail', pk=pk)
        else:
            review_form = ReviewChangeRequestForm()
    
    context = {
        'change_request': change_request,
        'diff': change_request.get_before_after_diff(),
        'comment_form': comment_form,
        'review_form': review_form,
        'can_review': request.user.is_staff and change_request.status == 'pending',
    }
    return render(request, 'change_requests/detail.html', context)


@login_required
@require_POST
def create_compound_change_request(request):
    """AJAX endpoint to create a change request for a compound"""
    try:
        data = json.loads(request.body)
        compound_id = data.get('compound_id')
        
        compound = get_object_or_404(Compound, id=compound_id)
        
        # Create form with submitted data
        form_data = {
            'title': data.get('title', ''),
            'description': data.get('description', ''),
            'name': data.get('name', ''),
            'description': data.get('compound_description', ''),
            'categories': data.get('categories', ''),
        }
        
        form = CompoundChangeRequestForm(form_data, compound=compound)
        
        if form.is_valid():
            # Get the changes data
            changes_data = form.get_changes_data()
            
            if not changes_data:
                return JsonResponse({
                    'success': False,
                    'error': 'No changes detected'
                })
            
            # Create the change request
            change_request = form.save(commit=False)
            change_request.requested_by = request.user
            change_request.content_type = ContentType.objects.get_for_model(Compound)
            change_request.object_id = compound.id
            change_request.changes_data = changes_data
            
            # Auto-approve for staff/superuser
            if request.user.is_staff or request.user.is_superuser:
                change_request.status = 'approved'
                change_request.reviewed_by = request.user
                change_request.reviewed_at = timezone.now()
                change_request.review_notes = 'Auto-approved (staff/superuser)'
            
            change_request.save()
            
            # Auto-apply if approved
            if change_request.status == 'approved':
                try:
                    change_request.apply_changes(request.user)
                    message = "Changes have been applied immediately."
                except Exception as e:
                    message = f"Change request created but error applying: {str(e)}"
            else:
                message = "Change request submitted for review."
            
            return JsonResponse({
                'success': True,
                'message': message,
                'change_request_id': change_request.id,
                'status': change_request.status
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def apply_change_request(request, pk):
    """Apply an approved change request"""
    if not request.user.is_staff:
        messages.error(request, "Only staff can apply change requests.")
        return redirect('change_requests:detail', pk=pk)
    
    change_request = get_object_or_404(ChangeRequest, pk=pk)
    
    if change_request.status not in ['approved']:
        messages.error(request, "Only approved change requests can be applied.")
        return redirect('change_requests:detail', pk=pk)
    
    try:
        # Store before data for audit trail
        obj = change_request.content_object
        before_data = {}
        for field_name in change_request.changes_data.keys():
            if hasattr(obj, field_name):
                before_data[field_name] = getattr(obj, field_name)
        
        # Apply the changes
        change_request.apply_changes(request.user)
        
        # Store after data for audit trail
        after_data = {}
        for field_name in change_request.changes_data.keys():
            if hasattr(obj, field_name):
                after_data[field_name] = getattr(obj, field_name)
        
        # Create audit trail record
        AppliedChange.objects.create(
            change_request=change_request,
            before_data=before_data,
            after_data=after_data,
            applied_by=request.user
        )
        
        messages.success(request, "Change request applied successfully.")
        
    except Exception as e:
        messages.error(request, f"Error applying change request: {str(e)}")
    
    return redirect('change_requests:detail', pk=pk)
