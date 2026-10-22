from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Block, Plot, Project


class BlockWriteSerializer(serializers.Serializer):
    """Writable block metadata; organization is fixed from the request context."""

    name = serializers.CharField(max_length=100)
    code = serializers.CharField(max_length=50)
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all(), required=False, allow_null=True)

    def validate(self, attrs):
        organization = self.context["organization"]
        instance = self.instance

        values = {
            field: getattr(instance, field)
            for field in self.fields
            if instance is not None
        }
        values.update(attrs)
        if values.get("project") and values["project"].organization_id != organization.id:
            raise serializers.ValidationError({"project": "Use a project in this organization."})
        candidate = Block(
            pk=instance.pk if instance else None,
            organization=organization,
            **values,
        )
        if instance is not None:
            candidate._state.adding = False
        try:
            candidate.full_clean()
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error
        return attrs

    def create(self, validated_data):
        block = Block(organization=self.context["organization"], **validated_data)
        block.save()
        return block

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.full_clean()
        instance.save()
        return instance


class PlotWriteSerializer(serializers.Serializer):
    """Writable plot metadata only; status is intentionally excluded until Phase 3."""

    block = serializers.PrimaryKeyRelatedField(queryset=Block.objects.all())
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all(), required=False, allow_null=True)
    plot_number = serializers.CharField(max_length=50)
    size = serializers.DecimalField(max_digits=12, decimal_places=2)
    plot_type = serializers.ChoiceField(choices=Plot.PlotType.choices, required=False)
    rate_per_sq_unit = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    total_price = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, allow_null=True
    )
    facing = serializers.CharField(max_length=50, required=False, allow_blank=True)
    dimensions = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        organization = self.context["organization"]
        instance = self.instance
        block = attrs.get("block", instance.block if instance else None)
        project = attrs.get("project", instance.project if instance else None)
        errors = {}

        if block and block.organization_id != organization.id:
            errors["block"] = "Use a block in this organization."
        if project and project.organization_id != organization.id:
            errors["project"] = "Use a project in this organization."
        if project and block and block.project_id and block.project_id != project.id:
            errors["project"] = "Project must match the selected block."
        if errors:
            raise serializers.ValidationError(errors)

        values = {
            field: getattr(instance, field)
            for field in self.fields
            if instance is not None
        }
        values.update(attrs)
        candidate = Plot(
            pk=instance.pk if instance else None,
            organization=organization,
            created_by=instance.created_by if instance else self.context["request"].user,
            status=instance.status if instance else Plot.Status.AVAILABLE,
            **values,
        )
        if instance is not None:
            candidate._state.adding = False
        try:
            candidate.full_clean()
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error
        return attrs

    def create(self, validated_data):
        plot = Plot(
            organization=self.context["organization"],
            created_by=self.context["request"].user,
            **validated_data,
        )
        plot.save()
        return plot

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.full_clean()
        instance.save()
        return instance
