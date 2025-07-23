from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse


@api_view(['GET'])
@permission_classes([AllowAny])
def api_root(request, format=None):
    """
    API Root - Lists all available API endpoints
    """
    return Response({
        'message': 'Welcome to the Neurobin API',
        'endpoints': {
            'authentication': {
                'obtain_token': reverse('token_obtain_pair', request=request, format=format),
                'refresh_token': reverse('token_refresh', request=request, format=format),
            },
            'compounds': {
                'compound_categories': request.build_absolute_uri('/api/compounds/compoundcategories/'),
                'targets': request.build_absolute_uri('/api/compounds/target/'),
                'mechanisms_of_action': request.build_absolute_uri('/api/compounds/compoundmechanismofaction/'),
                'compounds': request.build_absolute_uri('/api/compounds/compound/'),
                'compound_ratings': request.build_absolute_uri('/api/compounds/compoundrating/'),
                'safety_screenings': request.build_absolute_uri('/api/compounds/compoundsafetyscreening/'),
            },
            'accounts': {
                'users': request.build_absolute_uri('/api/accounts/user/'),
                'user_profiles': request.build_absolute_uri('/api/accounts/userprofile/'),
            },
            'logs': {
                'intake_logs': request.build_absolute_uri('/api/logs/intakelog/'),
            },
            'research': {
                'research_snippets': request.build_absolute_uri('/api/research/researchsnippet/'),
                'snippet_reviews': request.build_absolute_uri('/api/research/snippetreview/'),
                'snippet_tags': request.build_absolute_uri('/api/research/snippettag/'),
                'snippet_tagging': request.build_absolute_uri('/api/research/snippettagging/'),
                'user_roles': request.build_absolute_uri('/api/research/userrole/'),
                'research_settings': request.build_absolute_uri('/api/research/researchsettings/'),
                'snippet_comments': request.build_absolute_uri('/api/research/snippetcomment/'),
            }
        },
        'documentation': 'See API_DOCUMENTATION.md for detailed usage information'
    })
