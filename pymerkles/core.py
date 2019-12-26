from typing import Callable, NewType, Optional, Any, cast, List as PyList, BinaryIO
from abc import ABCMeta, ABC, abstractmethod
from pymerkles.tree import Node, Root, RootNode, zero_node

OFFSET_BYTE_LENGTH = 4


class TypeDef(ABCMeta):
    @classmethod
    @abstractmethod
    def coerce_view(mcs, v: Any) -> "View":
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def default_node(mcs) -> Node:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def view_from_backing(mcs, node: Node, hook: Optional["ViewHook"]) -> "View":
        raise NotImplementedError

    @classmethod
    def default(mcs, hook: Optional["ViewHook"]) -> "View":
        return mcs.view_from_backing(mcs.default_node(), hook)

    @classmethod
    def is_fixed_byte_length(mcs) -> bool:
        raise NotImplementedError

    @classmethod
    def type_byte_length(mcs) -> int:
        raise Exception("type is dynamic length, or misses overrides. Cannot get type byte length.")

    @classmethod
    @abstractmethod
    def min_byte_length(mcs) -> int:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def max_byte_length(mcs) -> int:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_bytes(mcs, bytez: bytes) -> "View":
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def deserialize(mcs, stream: BinaryIO, scope: int) -> "View":
        raise NotImplementedError


class FixedByteLengthTypeHelper(TypeDef):
    @classmethod
    def is_fixed_byte_length(mcs) -> bool:
        return True

    @classmethod
    def type_byte_length(mcs) -> int:
        raise NotImplementedError

    @classmethod
    def min_byte_length(mcs) -> int:
        return mcs.type_byte_length()

    @classmethod
    def max_byte_length(mcs) -> int:
        return mcs.type_byte_length()

    @classmethod
    def deserialize(mcs, stream: BinaryIO, scope: int) -> "View":
        n = mcs.type_byte_length()
        if n > scope:
            raise Exception(f"scope {scope} is not sufficient for expected byte length {n}")
        return mcs.from_bytes(stream.read(n))


class View(ABC, object, metaclass=TypeDef):
    @classmethod
    def coerce_view(cls, v: "View") -> "View":
        return cls.__class__.coerce_view(v)

    @classmethod
    def default_node(cls) -> Node:
        return cls.__class__.default_node()

    @classmethod
    def view_from_backing(cls, node: Node, hook: Optional["ViewHook"]) -> "View":
        return cls.__class__.view_from_backing(node, hook)

    @classmethod
    def default(cls, hook: Optional["ViewHook"]) -> "View":
        return cls.__class__.default(hook)

    @abstractmethod
    def get_backing(self) -> Node:
        raise NotImplementedError

    @abstractmethod
    def set_backing(self, value):
        raise NotImplementedError

    @abstractmethod
    def value_byte_length(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def as_bytes(self) -> bytes:
        raise NotImplementedError

    def serialize(self, stream: BinaryIO) -> int:
        out = self.as_bytes()
        stream.write(out)
        return len(out)


class FixedByteLengthViewHelper(View, metaclass=FixedByteLengthTypeHelper):
    def value_byte_length(self) -> int:
        return self.__class__.type_byte_length()


class BackedView(View, metaclass=TypeDef):
    _hook: Optional["ViewHook"]
    _backing: Node

    @classmethod
    def view_from_backing(cls, node: Node, hook: Optional["ViewHook"]) -> "View":
        return cls(backing=node, hook=hook)

    def __new__(cls, backing: Optional[Node] = None, hook=None, **kwargs):
        if backing is None:
            backing = cls.default_node()
        out = super().__new__(cls, **kwargs)
        out._backing = backing
        out._hook = hook
        return out

    def get_backing(self) -> Node:
        return self._backing

    def set_backing(self, value):
        self._backing = value
        # Propagate up the change if the view is hooked to a super view
        if self._hook is not None:
            self._hook(self)


ViewHook = NewType("ViewHook", Callable[[View], None])


class BasicTypeHelperDef(FixedByteLengthTypeHelper, TypeDef):
    @classmethod
    def default_node(mcs) -> Node:
        return zero_node(0)

    @classmethod
    @abstractmethod
    def type_byte_length(mcs) -> int:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_bytes(mcs, bytez: bytes) -> "BasicView":
        raise NotImplementedError

    @classmethod
    def view_from_backing(mcs, node: Node, hook: Optional["ViewHook"]) -> "View":
        if isinstance(node, RootNode):
            size = mcs.type_byte_length()
            return mcs.from_bytes(node.root[0:size])
        else:
            raise Exception("cannot create basic view from composite node!")

    @classmethod
    def basic_view_from_backing(mcs, node: RootNode, i: int) -> "BasicView":
        size = mcs.type_byte_length()
        return mcs.from_bytes(node.root[i*size:(i+1)*size])

    @classmethod
    def pack_views(mcs, views: PyList[View]) -> PyList[Node]:
        elems_per_chunk = 32 // mcs.type_byte_length()
        chunk: RootNode = zero_node(0)
        i = 0
        out = []
        for v in views:
            if not isinstance(v.__class__, mcs):
                raise Exception("element is not the expected type")
            chunk = cast(BasicView, v).backing_from_base(chunk, i % elems_per_chunk)
            i += 1
            if i % elems_per_chunk == 0:
                out.append(chunk)
        if i % elems_per_chunk != 0:
            out.append(chunk)
        return out


class BasicView(FixedByteLengthViewHelper, ABC, metaclass=BasicTypeHelperDef):
    @classmethod
    def default_node(cls) -> Node:
        return cls.__class__.default_node()

    @classmethod
    def from_bytes(cls, bytez: bytes) -> "BasicView":
        return cls.__class__.from_bytes(bytez)

    @classmethod
    def view_from_backing(cls, node: Node, hook: Optional["ViewHook"]) -> "View":
        return cls.__class__.view_from_backing(node, hook)

    @classmethod
    def basic_view_from_backing(cls, node: RootNode, i: int) -> "BasicView":
        return cls.__class__.basic_view_from_backing(node, i)

    def backing_from_base(self, base: RootNode, i: int) -> RootNode:
        section_bytez = self.as_bytes()
        chunk_bytez = base.root[:len(section_bytez)*i] + section_bytez + base.root[len(section_bytez)*(i+1):]
        return RootNode(Root(chunk_bytez))

    def get_backing(self) -> Node:
        bytez = self.as_bytes()
        return RootNode(Root(bytez + b"\x00" * (32 - len(bytez))))

    def set_backing(self, value):
        raise Exception("cannot change the backing of a basic view")
