from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import importlib.util
import inspect
from io import BufferedReader, BytesIO
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Type, Union

from .compiler import CompiledKSY

from kaitaistruct import KaitaiStruct

PARSER_DIR: Path = Path(__file__).absolute().parent / "parsers"
MANIFEST_FILE: Path = PARSER_DIR / "manifest.json"

with open(MANIFEST_FILE, "r") as f:
    MANIFEST: Dict[str, Dict[str, Any]] = json.load(f)
COMPILED_INFO_BY_KSY: Dict[str, CompiledKSY] = {
    ksy_path: CompiledKSY(
        class_name=component["class_name"],
        python_path=PARSER_DIR / component["python_path"],
        dependencies=(
            CompiledKSY(class_name=dep["class_name"], python_path=PARSER_DIR / dep["python_path"])
            for dep in component["dependencies"]
        )
    )
    for ksy_path, component in MANIFEST.items()
}
del MANIFEST

_IMPORTED_SPECS: Set[Path] = set()
_PARSERS_BY_KSY: Dict[str, Type[KaitaiStruct]] = {}


def import_spec(compiled: CompiledKSY) -> Optional[Type[KaitaiStruct]]:
    if compiled.python_path in _IMPORTED_SPECS:
        return None
    _IMPORTED_SPECS.add(compiled.python_path)
    module_name = compiled.python_path.name
    assert module_name.lower().endswith(".py")
    module_name = module_name[:-3]
    module_name = f"{__name__}.parsers.{module_name}"
    spec = importlib.util.spec_from_file_location(module_name, compiled.python_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for objname, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and objname == compiled.class_name:
            return obj
    raise ImportError(f"Could not find parser class {compiled.class_name!r} in {compiled.python_path}")


@dataclass(unsafe_hash=True, order=True, frozen=True)
class Segment:
    start: int
    end: int


class ASTNode:
    """Represents an element in a parse."""

    def __init__(
            self,
            name: str,
            segment: Segment,
            offset: int,
            parent: Optional["CompoundNode"] = None
    ):
        self.name: str = name
        self.segment: Segment = segment
        self.offset: int = offset
        if parent is None:
            if not isinstance(self, RootNode):
                raise ValueError(f"Only a RootNode can have no parent, not {self!r}")
            self.root: RootNode = self
            self.level: int = 0
        else:
            self.root = parent.root
            self.level = parent.level + 1
        self.parent: Optional[CompoundNode] = parent

    @property
    def start(self) -> int:
        return self.offset + self.segment.start

    @property
    def end(self) -> int:
        return self.offset + self.segment.end

    @property
    def raw_value(self):
        """Sequence of bytes of this segment."""
        return self.root.get_value(self.start, self.end)

    @property
    def size(self) -> int:
        return self.end - self.start

    def __repr__(self):
        return f"{self.name}({self.__class__.__name__}) [{self.start}:{self.end}]"


class ValueNode(ASTNode):
    """A leaf in the parse tree."""

    TYPES = (int, float, str, bytes, Enum)

    def __init__(self, value: bytes, *args, **kwargs):
        self._value: bytes = value
        super().__init__(*args, **kwargs)

    @property
    def value(self) -> bytes:
        return self._value

    def __repr__(self):
        return f"{self.name}({self.__class__.__name__}<{self.value.__class__.__name__}>) [{self.start}:{self.end}]"


class CompoundNode(ASTNode, ABC):
    """A node that can have children"""

    def __init__(self, obj: KaitaiStruct, *args, **kwargs):
        self.obj: KaitaiStruct = obj
        super().__init__(*args, **kwargs)
        self._children: Optional[List[ASTNode]] = None

    @property
    def children(self) -> List[ASTNode]:
        if self._children is None:
            self._children = list(self.explore())
        return self._children

    @abstractmethod
    def explore(self) -> Iterator[ASTNode]:
        raise NotImplementedError()

    def make_child(
            self,
            obj: KaitaiStruct,
            name: str,
            segment: Segment,
            offset: int,
    ) -> ASTNode:
        if isinstance(obj, KaitaiStruct):
            node_class = StructNode
        elif isinstance(obj, ValueNode.TYPES):
            node_class = ValueNode
        elif isinstance(obj, list):
            node_class = ArrayNode
        else:
            raise TypeError(f"Unknown object type: {type(obj)}")

        return node_class(obj, name, segment, offset, self)


class StructNode(CompoundNode):
    """Represents node of the subtype."""

    def explore(self) -> Iterator[ASTNode]:
        for name in self.obj.SEQ_FIELDS:
            markers = self.obj._debug[name].copy()
            if "arr" in markers:
                del markers["arr"]
            segment = Segment(**markers)
            offset = self.offset
            if isinstance(self.parent, StructNode):
                if self.obj._io != self.parent.obj._io:
                    offset = self.start
            yield self.make_child(getattr(self.obj, name), name, segment, offset)


class ArrayNode(CompoundNode):
    """Represents node of array of subtype items."""

    def explore(self) -> Iterator[ASTNode]:
        for i, obj in enumerate(self.obj):
            markers = self.parent.obj._debug[self.name]["arr"][i]
            segment = Segment(**markers)
            name = f"{self.name}[{i}]"
            yield self.make_child(obj, name, segment, self.offset)


class RootNode(StructNode):
    def __init__(self, buffer: bytes, obj: KaitaiStruct):
        self.buffer: bytes = buffer
        super().__init__(obj, name=obj.__class__.__name__, segment=Segment(0, len(self.buffer)), offset=0)

    def get_value(self, start, end):
        return self.buffer[start:end]


def build(struct):
    """Interface method, shorthand for RootNode()."""

    _io = struct._io._io
    if isinstance(_io, BytesIO):
        buffer = _io.getbuffer().tobytes()
    elif isinstance(_io, BufferedReader):
        with open(struct._io._io.name, 'rb') as f:
            buffer = f.read()
    else:
        raise TypeError('Unsupported stream type')

    return RootNode(buffer, struct)


class KaitaiInspector:
    def __init__(self, struct: KaitaiStruct):
        self.struct: KaitaiStruct = struct
        print(build(struct).children)


class KaitaiParser:
    def __init__(self, struct_type: Type[KaitaiStruct]):
        self.struct_type: Type[KaitaiStruct] = struct_type

    @staticmethod
    def load(ksy_path: str) -> "KaitaiParser":
        """Returns a parser for the given KSY file and input file.

        The KSY file is specified as a relative path to the file within the Kaitai struct format library.
        Examples:

             "executable/dos_mz.ksy"
             "image/jpeg.ksy"
             "network/pcap.ksy"

        """
        if ksy_path not in _PARSERS_BY_KSY:
            if ksy_path not in COMPILED_INFO_BY_KSY:
                raise KeyError(ksy_path)
            info = COMPILED_INFO_BY_KSY[ksy_path]
            _PARSERS_BY_KSY[ksy_path] = import_spec(info)  # type: ignore
        return KaitaiParser(_PARSERS_BY_KSY[ksy_path])

    def parse(self, input_file_path: Union[str, Path]) -> KaitaiInspector:
        if isinstance(input_file_path, Path):
            input_file_path = str(input_file_path)

        struct = self.struct_type.from_file(input_file_path)
        struct._read()
        return KaitaiInspector(struct)
