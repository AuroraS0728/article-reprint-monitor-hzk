from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User


class EmptySerializer(serializers.Serializer[object]):
    pass


class LoginSerializer(serializers.Serializer[object]):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, write_only=True)


class CurrentUserSerializer(serializers.Serializer[object]):
    id = serializers.IntegerField()
    username = serializers.CharField()
    role = serializers.CharField()
    must_change_password = serializers.BooleanField(required=False)


class UserManagementSerializer(serializers.ModelSerializer[User]):
    password = serializers.CharField(write_only=True, required=False, min_length=10)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "role",
            "is_active",
            "must_change_password",
            "password",
        ]
        read_only_fields = ["must_change_password"]

    def create(self, validated_data: dict[str, object]) -> User:
        password = validated_data.pop("password", None)
        if not isinstance(password, str):
            raise serializers.ValidationError({"password": "创建用户时必须设置密码。"})
        validate_password(password)
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance: User, validated_data: dict[str, object]) -> User:
        password = validated_data.pop("password", None)
        if password is not None:
            if not isinstance(password, str):
                raise serializers.ValidationError({"password": "密码格式无效。"})
            validate_password(password, user=instance)
            instance.set_password(password)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        update_fields = (
            [*validated_data.keys(), "password"]
            if password is not None
            else list(validated_data.keys())
        )
        if update_fields:
            instance.save(update_fields=update_fields)
        return instance


class ChangePasswordSerializer(serializers.Serializer[object]):
    old_password = serializers.CharField(write_only=True, max_length=128)
    new_password = serializers.CharField(write_only=True, min_length=10, max_length=128)
