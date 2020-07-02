import logging

from django.conf import settings
from django.contrib import messages
from django.urls import reverse

from django.shortcuts import HttpResponseRedirect, render, get_object_or_404
from django.views.generic import ListView, CreateView, DeleteView
from django.core.mail import send_mail
from django.template.loader import get_template
from braces.views import LoginRequiredMixin

from booking.models import DropInBlockConfig, CourseBlockConfig


from activitylog.models import ActivityLog

logger = logging.getLogger(__name__)


# TODO
# List all available blocks (dropin and course)
# Order with relevant eventtype/coursetype blocks first and highlighted
# Grey out ones that user already has
# Purchase buttons for available ones
# login required, disclaimer required, data privacy required

def dropin_block_purchase_view(request, event_type):
    pass


def course_block_purchase_view(request, course_type):
    pass