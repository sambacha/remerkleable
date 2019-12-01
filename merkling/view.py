from typing import Callable, NewType, Optional
from merkling.tree import Link, Node, Root, RootNode, subtree_fill_to_length, to_gindex, zero_node, merkle_hash


# Get the depth required for a given element count
# (in out): (0 0), (1 1), (2 1), (3 2), (4 2), (5 3), (6 3), (7 3), (8 3), (9 4)
def get_depth(elem_count: int) -> int:
    return (elem_count - 1).bit_length()


class TypeDef(type):
    def default_node(self) -> Node:
        raise NotImplementedError

    def view_from_backing(self, node: Node, hook: Optional["ViewHook"]) -> "View":
        raise NotImplementedError

    def default(self, hook: Optional["ViewHook"]) -> "View":
        return self.view_from_backing(self.default_node(), hook)


class TypeBase(type, metaclass=TypeDef):
    pass


class View(object, metaclass=TypeBase):

    def get_backing(self) -> Node:
        raise NotImplementedError

    def set_backing(self, value):
        raise NotImplementedError


class BackedType(TypeBase, metaclass=TypeDef):

    def view_from_backing(cls, node: Node, hook: Optional["ViewHook"]) -> "View":
        return cls(backing=node, hook=hook)


class BackedView(View, metaclass=BackedType):
    hook: Optional["ViewHook"]
    _backing: Node

    def __init__(self, *args, **kw):
        if "backing" in kw:
            self._backing = kw.pop("backing")
        else:
            self._backing = self.__class__.default_node()
        self.hook = kw.pop("hook", None)
        super().__init__(*args, **kw)

    def get_backing(self) -> Node:
        return self._backing

    def set_backing(self, value):
        self._backing = value
        # Propagate up the change if the view is hooked to a super view
        if self.hook is not None:
            self.hook(self)


ViewHook = NewType("ViewHook", Callable[[View], None])


class SubtreeType(BackedType):
    def depth(cls):
        raise NotImplementedError


class SubtreeView(BackedView, metaclass=SubtreeType):

    def get(self, i: int) -> View:
        return self.__class__.__class__.view_from_backing(
            self.get_backing().getter(to_gindex(i, self.__class__.depth())), self.hook)

    def set(self, i: int, v: View) -> None:
        setter_link: Link = self.get_backing().setter(to_gindex(i, self.__class__.depth()))
        self.set_backing(setter_link(v.get_backing()))


class BasicTypeDef(TypeDef):
    def default_node(cls) -> Node:
        return zero_node(0)

    def byte_length(cls) -> int:
        raise NotImplementedError

    def from_bytes(cls, bytez: bytes, byteorder: str):
        raise NotImplementedError

    def view_from_backing(cls, node: Node, hook: Optional["ViewHook"]) -> "View":
        if isinstance(node, RootNode):
            size = cls.byte_length()
            return cls.from_bytes(node.root[0:size], byteorder='little')
        else:
            raise Exception("cannot create basic view from composite node!")

    def basic_view_from_backing(cls, node: RootNode, i: int) -> "BasicView":
        size = cls.byte_length()
        return cls.from_bytes(node.root[i*size:(i+1)*size], byteorder='little')


class BasicTypeBase(TypeBase, metaclass=BasicTypeDef):
    pass


class BasicView(View, metaclass=BasicTypeBase):
    def backing_from_base(self, base: RootNode, i: int) -> RootNode:
        raise NotImplementedError

    def to_bytes(self, length: int, byteorder: str) -> bytes:
        raise NotImplementedError

    def get_backing(self) -> Node:
        return RootNode(Root(self.to_bytes(length=32, byteorder='little')))

    def set_backing(self, value):
        raise Exception("cannot change the backing of a basic view")


class VectorType(SubtreeType):
    def depth(cls) -> int:
        return get_depth(cls.length())

    def element_type(cls) -> TypeDef:
        raise NotImplementedError

    def length(cls) -> int:
        raise NotImplementedError

    def default_node(cls) -> Node:
        elem = cls.element_type().default_node()
        return subtree_fill_to_length(elem, cls.depth(), cls.length())

    def __getitem__(self, params):
        (element_type, length) = params

        class SpecialVectorType(VectorType):
            def element_type(cls) -> TypeDef:
                return element_type

            def length(cls) -> int:
                return length

        class SpecialVectorView(Vector, metaclass=SpecialVectorType):
            pass

        return SpecialVectorView


class Vector(SubtreeView, metaclass=VectorType):
    def get(self, i: int) -> View:
        if i > self.__class__.length():
            raise IndexError
        return super().get(i)

    def set(self, i: int, v: View) -> None:
        if i > self.__class__.length():
            raise IndexError
        super().set(i, v)


class Uint64Type(BasicTypeBase, metaclass=BasicTypeDef):
    @classmethod
    def byte_length(mcs) -> int:
        return 8


class Uint64View(int, BasicView, metaclass=Uint64Type):
    pass


SimpleVec = Vector[Uint64Type, 512]
print(SimpleVec)
data: Vector = SimpleVec()
print(data)
print(data.get_backing().merkle_root(merkle_hash).hex())
data.set(1, Uint64View(123))
print(data.get_backing().merkle_root(merkle_hash).hex())
data.set(10, Uint64View(42))
print(data.get_backing().merkle_root(merkle_hash).hex())
data.set(1, Uint64View(0))
print(data.get_backing().merkle_root(merkle_hash).hex())
data.set(10, Uint64View(0))
print(data.get_backing().merkle_root(merkle_hash).hex())

