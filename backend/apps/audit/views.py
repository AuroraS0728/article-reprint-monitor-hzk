from rest_framework import generics

from apps.core.permissions import IsAdministrator

from .models import OperationLog
from .serializers import OperationLogSerializer


class OperationLogListView(generics.ListAPIView[OperationLog]):
    permission_classes = [IsAdministrator]
    serializer_class = OperationLogSerializer
    queryset = OperationLog.objects.select_related("actor").all()
