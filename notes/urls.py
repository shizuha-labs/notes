"""
URL configuration for Shizuha Notes API.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'notebooks', views.NotebookViewSet, basename='notebook')
router.register(r'tags', views.TagViewSet, basename='tag')
router.register(r'notes', views.NoteViewSet, basename='note')
router.register(r'attachments', views.AttachmentViewSet, basename='attachment')

urlpatterns = [
    # Search endpoint
    path('search/', views.SearchView.as_view(), name='search'),

    # Trash operations
    path('trash/', views.TrashView.as_view(), name='trash'),

    # Shared with me
    path('shared/', views.SharedWithMeView.as_view(), name='shared-with-me'),

    # Public note view (no auth required)
    path('public/<str:token>/', views.PublicNoteView.as_view(), name='public-note'),

    # Bulk operations
    path('notes/bulk-delete/', views.BulkNoteView.as_view(), {'action': 'delete'}, name='bulk-delete'),
    path('notes/bulk-move/', views.BulkNoteView.as_view(), {'action': 'move'}, name='bulk-move'),
    path('notes/bulk-tag/', views.BulkNoteView.as_view(), {'action': 'tag'}, name='bulk-tag'),

    # Router URLs
    path('', include(router.urls)),
]
