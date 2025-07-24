# Neurobin Admin Access Guide

## Overview

This guide covers administrative features and access patterns for the Neurobin platform. The system provides multiple levels of administrative control through Django Admin, API endpoints, and frontend interfaces.

## Admin User Types

### Superuser (Full Admin)
- **Access Level:** Complete system control
- **Capabilities:** All CRUD operations, user management, system settings
- **Creation:** `python manage.py createsuperuser`

### Staff User
- **Access Level:** Content management
- **Capabilities:** Compound editing, research moderation, user content review
- **Creation:** Set `is_staff=True` in Django Admin

### Trusted Reviewer
- **Access Level:** Research validation
- **Capabilities:** Review research snippets, higher vote weight
- **Creation:** Set role in Research → User Roles

## Django Admin Interface

### Access URL
```
https://neurob.in/admin/
http://localhost:9000/admin/  (development)
```

### Admin Models Overview

#### Compounds Management
```
Admin → Compounds App
├── Compounds                    # Core compound data
├── Compound Categories          # Classification system
├── Targets                      # Molecular targets
├── Compound Mechanisms          # Mechanism of action
├── Compound Ratings            # User ratings (5-star)
├── Compound Safety Screening   # Safety assessments
├── Effect Windows              # Pharmacokinetic data
├── Compound Target Interactions # Target binding data
└── Compound-to-Compound Interactions # Drug interactions
```

#### Research Management
```
Admin → Research App
├── Research Snippets           # Community research content
├── Snippet Reviews             # Peer review system
├── Snippet Tags               # Content categorization
├── Snippet Taggings           # Tag associations
├── Snippet Comments           # Discussion system
├── User Roles                 # Permission system
└── Research Settings          # Global configuration
```

#### User Management
```
Admin → Accounts App
├── Users                      # Django auth users
├── User Profiles             # Extended profile data
└── Groups                    # Permission groups
```

#### Logging & Analytics
```
Admin → Logs App
└── Intake Logs               # User compound tracking
```

#### Change Management
```
Admin → Change Requests App
├── Change Requests           # Collaborative editing
├── Change Request Comments   # Review discussions
└── Applied Changes          # Audit trail
```

## Administrative Tasks

### 1. Compound Management

#### Adding New Compounds
1. Navigate to **Compounds → Compounds**
2. Click **Add Compound**
3. Fill required fields:
   - **Name:** Unique compound name
   - **Slug:** Auto-generated URL slug
   - **Description:** Detailed description
   - **SMILES:** Molecular structure notation
   - **Categories:** Select applicable categories
   - **Mechanisms:** Link to mechanism data

#### Bulk Compound Operations
```python
# Django shell commands
python manage.py shell

# Bulk category assignment
from compounds.models import Compound, CompoundCategories
nootropic_cat = CompoundCategories.objects.get(name="Nootropics")
compounds = Compound.objects.filter(name__in=["Modafinil", "Piracetam"])
for compound in compounds:
    compound.categories.add(nootropic_cat)
```

#### Compound Interaction Management
1. Navigate to **Compounds → Compound-to-Compound Interactions**
2. Set up drug interactions:
   - **Compound A & B:** Select interacting compounds
   - **Target:** Shared molecular target
   - **Interaction Type:** Synergistic/Antagonistic/etc.
   - **Confidence:** Low/Medium/High
   - **Source:** Reference material

### 2. Research Content Moderation

#### Review Research Snippets
1. Navigate to **Research → Research Snippets**
2. Filter by **Status:** Submitted/Flagged
3. Review content quality:
   - Verify scientific accuracy
   - Check source citations
   - Assess relevance to compound
4. Update **Status:** Validated/Rejected

#### Manage Community Reviews
1. Navigate to **Research → Snippet Reviews**
2. Monitor voting patterns:
   - Check for vote manipulation
   - Review flagged content
   - Moderate user conflicts

#### Configure Research Settings
1. Navigate to **Research → Research Settings**
2. Adjust thresholds:
   - **Validation Threshold:** Votes needed for approval
   - **Flagging Threshold:** Rejection votes for flagging
   - **High Confidence Threshold:** Votes for high confidence

### 3. User Administration

#### User Role Management
1. Navigate to **Research → User Roles**
2. Assign roles:
   - **Authenticated:** Standard users
   - **Trusted Reviewer:** Experienced contributors
   - **Moderator:** Content moderators
   - **Admin:** Full access

#### User Profile Moderation
1. Navigate to **Accounts → User Profiles**
2. Review and moderate:
   - Profile images
   - Bio content
   - External links

#### Ban/Suspend Users
1. Navigate to **Users**
2. Edit problematic user:
   - Uncheck **Active** to suspend
   - Remove **Staff status** to revoke admin access
   - Add to moderation group for restrictions

### 4. System Configuration

#### Intake Log Management
1. Navigate to **Logs → Intake Logs**
2. Monitor usage patterns:
   - Popular compounds
   - Usage frequency
   - User behavior patterns

#### Change Request Approval
1. Navigate to **Change Requests → Change Requests**
2. Review proposed changes:
   - Verify change accuracy
   - Check user permissions
   - Approve or reject with comments

### 5. Data Export and Reporting

#### Export User Data
```python
# Django shell - Export compound usage
from logs.models import IntakeLog
import csv

with open('intake_report.csv', 'w') as f:
    writer = csv.writer(f)
    writer.writerow(['User', 'Compound', 'Amount', 'Date'])
    for log in IntakeLog.objects.all():
        writer.writerow([log.user.username, log.compound.name, 
                        log.amount, log.taken_at])
```

#### Research Analytics
```python
# Research snippet statistics
from research.models import ResearchSnippet, SnippetReview
from django.db.models import Count

# Most researched compounds
compound_research = ResearchSnippet.objects.values('compound__name').annotate(
    snippet_count=Count('id')
).order_by('-snippet_count')

# User contribution stats
user_contributions = ResearchSnippet.objects.values('created_by__username').annotate(
    contribution_count=Count('id')
).order_by('-contribution_count')
```

## API Administration

### Admin API Endpoints

#### Compound Management API
```bash
# List all compounds with admin view
curl -H "Authorization: Bearer $TOKEN" \
     "https://neurob.in/api/compounds/compound/?is_staff=true"

# Update compound data
curl -X PATCH \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"description": "Updated description"}' \
     "https://neurob.in/api/compounds/compound/1/"
```

#### Research Moderation API
```bash
# Get pending research snippets
curl -H "Authorization: Bearer $TOKEN" \
     "https://neurob.in/api/research/snippets/?status=submitted"

# Approve research snippet
curl -X PATCH \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"status": "validated"}' \
     "https://neurob.in/api/research/snippets/1/"
```

#### User Management API
```bash
# List users with admin details
curl -H "Authorization: Bearer $TOKEN" \
     "https://neurob.in/api/accounts/users/?admin_view=true"

# Update user permissions
curl -X PATCH \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"is_staff": true}' \
     "https://neurob.in/api/accounts/users/1/"
```

## Frontend Admin Controls

### Compound Detail Admin Features
When logged in as staff, compound detail pages show:
- **Edit Name:** Inline compound name editing
- **Edit Description:** Inline description editing
- **Add Mechanism:** Quick mechanism addition
- **Edit Categories:** Category management
- **Add Effect Window:** Pharmacokinetic data entry

### Research Snippet Moderation
Staff users can:
- **Review Snippets:** Validate/reject research content
- **Moderate Comments:** Edit/delete inappropriate comments
- **Manage Tags:** Create and assign content tags
- **Bulk Actions:** Perform actions on multiple snippets

## Security Best Practices

### Admin Account Security
1. **Strong Passwords:** Minimum 12 characters, mixed case, numbers, symbols
2. **Two-Factor Authentication:** Enable 2FA for admin accounts
3. **Regular Password Rotation:** Change passwords every 90 days
4. **Limited Admin Accounts:** Only create necessary admin accounts

### Permission Management
1. **Principle of Least Privilege:** Grant minimum required permissions
2. **Regular Permission Audits:** Review and revoke unnecessary permissions
3. **Role-Based Access:** Use groups for permission management
4. **Activity Monitoring:** Track admin actions for audit trails

### Data Protection
1. **Regular Backups:** Automated database and media backups
2. **Backup Encryption:** Encrypt sensitive backup data
3. **Access Logging:** Monitor all admin access attempts
4. **IP Restrictions:** Limit admin access by IP when possible

## Monitoring and Alerts

### System Health Monitoring
```python
# Custom management command for health checks
# management/commands/health_check.py

from django.core.management.base import BaseCommand
from django.db import connection
from compounds.models import Compound
from research.models import ResearchSnippet

class Command(BaseCommand):
    def handle(self, *args, **options):
        # Database connectivity
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        # Model accessibility
        compound_count = Compound.objects.count()
        snippet_count = ResearchSnippet.objects.count()
        
        self.stdout.write(f"System healthy: {compound_count} compounds, {snippet_count} snippets")
```

### User Activity Monitoring
```python
# Track admin actions with signals
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import logging

logger = logging.getLogger('admin_activity')

@receiver(post_save, sender=Compound)
def log_compound_change(sender, instance, created, **kwargs):
    if created:
        logger.info(f"New compound created: {instance.name}")
    else:
        logger.info(f"Compound updated: {instance.name}")
```

## Troubleshooting Common Issues

### Admin Interface Issues
1. **CSS Not Loading:** Run `python manage.py collectstatic`
2. **Permission Denied:** Check user `is_staff` and `is_superuser` flags
3. **Timeout Errors:** Optimize database queries, add pagination

### Content Issues
1. **Missing Compounds:** Check slug generation, verify database integrity
2. **Research Not Appearing:** Verify status and visibility settings
3. **User Data Missing:** Check foreign key relationships

### Performance Issues
1. **Slow Admin Pages:** Add database indexes, optimize queries
2. **Large Data Sets:** Implement pagination, add filtering options
3. **File Upload Issues:** Check media settings, disk space

## Backup and Recovery

### Admin Data Backup
```bash
# Create comprehensive backup
python manage.py dumpdata > neurobin_backup.json

# Restore from backup
python manage.py loaddata neurobin_backup.json
```

### Selective Data Export
```python
# Export specific app data
python manage.py dumpdata compounds > compounds_backup.json
python manage.py dumpdata research > research_backup.json
python manage.py dumpdata accounts > accounts_backup.json
```

## Custom Admin Actions

### Bulk Operations
```python
# admin.py - Custom bulk actions
def approve_research_snippets(modeladmin, request, queryset):
    queryset.update(status='validated')
approve_research_snippets.short_description = "Approve selected research snippets"

def bulk_assign_category(modeladmin, request, queryset):
    # Custom form for bulk category assignment
    pass
bulk_assign_category.short_description = "Bulk assign category"

class ResearchSnippetAdmin(admin.ModelAdmin):
    actions = [approve_research_snippets]
    
class CompoundAdmin(admin.ModelAdmin):
    actions = [bulk_assign_category]
```

---

**Admin Guide Version:** 1.0  
**Last Updated:** July 2025  
**Access Level:** Administrative Personnel Only