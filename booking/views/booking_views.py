from django.conf import settings
from django.contrib import messages

from django.shortcuts import get_object_or_404, HttpResponseRedirect, render
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound
from django.template.loader import get_template
from django.urls import reverse

from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView

from braces.views import LoginRequiredMixin

from activitylog.models import ActivityLog
from ..email_helpers import send_waiting_list_email, send_user_and_studio_emails
from ..models import Booking, Event, WaitingListUser
from ..utils import has_available_block, get_active_user_block
from .views_utils import DataPolicyAgreementRequiredMixin, DisclaimerRequiredMixin


...