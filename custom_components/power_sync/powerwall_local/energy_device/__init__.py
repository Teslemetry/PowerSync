"""Bundled Tesla energy-device messages using Home Assistant's protobuf runtime.

The private pool keeps these pinned schemas independent of packages installed by
other integrations. No runtime installation, global symbol registration, or
protobuf version override is performed. See README.md for schema provenance.
"""

from types import ModuleType
import sys

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.internal.enum_type_wrapper import EnumTypeWrapper

from ._descriptors import FILE_DESCRIPTOR_SET


_pool = descriptor_pool.DescriptorPool()
_files = descriptor_pb2.FileDescriptorSet.FromString(FILE_DESCRIPTOR_SET)
for _file in _files.file:
    # protoc --include_imports emits dependencies before their users, including
    # the well-known types. They belong to this pool too, not the default pool.
    _pool.Add(_file)


def _module(file_name: str) -> ModuleType:
    descriptor = _pool.FindFileByName(file_name)
    name = f"{__name__}.{file_name.removesuffix('.proto')}_pb2"
    module = ModuleType(name)
    module.DESCRIPTOR = descriptor
    for message_name, message in descriptor.message_types_by_name.items():
        cls = message_factory.GetMessageClass(message)
        cls.__module__ = name
        setattr(module, message_name, cls)
    for enum_name, enum in descriptor.enum_types_by_name.items():
        setattr(module, enum_name, EnumTypeWrapper(enum))
        for value in enum.values:
            setattr(module, value.name, value.number)
    sys.modules[name] = module
    return module


for _file in _files.file:
    if not _file.name.startswith("google/"):
        globals()[f"{_file.name.removesuffix('.proto')}_pb2"] = _module(_file.name)

del _files, _file
