"""Minimal protobuf models for Douyin IM response bodies."""

from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf.internal import builder as _builder


def _field(
    message,
    name: str,
    number: int,
    field_type: int,
    *,
    repeated: bool = False,
    type_name: str = "",
    oneof_index: int | None = None,
) -> None:
    field = message.field.add()
    field.name = name
    field.number = number
    field.label = 3 if repeated else 1
    field.type = field_type
    if type_name:
        field.type_name = type_name
    if oneof_index is not None:
        field.oneof_index = oneof_index


_file = _descriptor_pb2.FileDescriptorProto(name="Response.proto", package="oral.im", syntax="proto3")

_response = _file.message_type.add(name="Response")
_field(_response, "cmd", 1, 5)
_field(_response, "sequence_id", 2, 3)
_field(_response, "error_desc", 3, 9)
_field(_response, "message", 4, 9)
_field(_response, "inbox_type", 5, 3)
_field(_response, "body", 6, 11, type_name=".oral.im.ResponseBody")

_body = _file.message_type.add(name="ResponseBody")
_body.oneof_decl.add(name="body")
_field(
    _body,
    "new_message_notify",
    500,
    11,
    type_name=".oral.im.NewMessageNotify",
    oneof_index=0,
)
_field(
    _body,
    "create_conversation_v2_body",
    609,
    11,
    type_name=".oral.im.ConversationInfoList",
    oneof_index=0,
)
_field(
    _body,
    "get_conversation_info_list_v2_response_body",
    610,
    11,
    type_name=".oral.im.ConversationInfoList",
    oneof_index=0,
)

_notify = _file.message_type.add(name="NewMessageNotify")
_field(_notify, "conversation_id", 2, 9)
_field(_notify, "conversation_type", 3, 5)
_field(_notify, "notify_type", 4, 5)
_field(_notify, "message", 5, 11, type_name=".oral.im.MessageBody")

_message = _file.message_type.add(name="MessageBody")
_field(_message, "conversation_id", 1, 9)
_field(_message, "conversation_type", 2, 5)
_field(_message, "server_message_id", 3, 3)
_field(_message, "index_in_conversation", 4, 3)
_field(_message, "conversation_short_id", 5, 3)
_field(_message, "message_type", 6, 5)
_field(_message, "sender", 7, 3)
_field(_message, "content", 8, 9)

_conversation_list = _file.message_type.add(name="ConversationInfoList")
_field(
    _conversation_list,
    "conversation_info_list",
    1,
    11,
    repeated=True,
    type_name=".oral.im.ConversationInfo",
)

_conversation = _file.message_type.add(name="ConversationInfo")
_field(_conversation, "conversation_id", 1, 9)
_field(_conversation, "conversation_short_id", 2, 3)
_field(_conversation, "conversation_type", 3, 5)
_field(_conversation, "ticket", 4, 9)

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(_file.SerializeToString())
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, __name__, globals())
