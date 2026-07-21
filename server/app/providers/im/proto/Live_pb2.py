"""Minimal protobuf model for Douyin IM push frames."""

from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf.internal import builder as _builder


def _field(message, name: str, number: int, field_type: int, *, repeated: bool = False, type_name: str = "") -> None:
    field = message.field.add()
    field.name = name
    field.number = number
    field.label = 3 if repeated else 1
    field.type = field_type
    if type_name:
        field.type_name = type_name


_file = _descriptor_pb2.FileDescriptorProto(name="Live.proto", package="oral.im", syntax="proto3")

_headers = _file.message_type.add(name="HeadersList")
_field(_headers, "key", 1, 9)
_field(_headers, "value", 2, 9)

_frame = _file.message_type.add(name="PushFrame")
_field(_frame, "seqId", 1, 4)
_field(_frame, "logId", 2, 4)
_field(_frame, "service", 3, 4)
_field(_frame, "method", 4, 4)
_field(_frame, "headersList", 5, 11, repeated=True, type_name=".oral.im.HeadersList")
_field(_frame, "payloadEncoding", 6, 9)
_field(_frame, "payloadType", 7, 9)
_field(_frame, "payload", 8, 12)
_field(_frame, "logIdNew", 9, 9)

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(_file.SerializeToString())
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, __name__, globals())
