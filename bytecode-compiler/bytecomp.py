"""
Byte-compile trivial programs with if, while, globals, calls, and
a bit more.

I don't know if this mostly-functional style is the way to go;
fix_jumps() and especially JUMP_BACK are horrible. That part'd work
much better if bytecode had only relative jumps, instead of sometimes
relative sometimes absolute.

So how should we do this? Some possibilities:

  * Emit something like symbolic assembly, with a second pass making
    actual bytecode. The current scheme is really a variant of this
    now, with fix_jumps() as the second pass. 

  * Emit code statefully, so you know absolute addresses (fixing up
    references as you get to them). I expect this to need more lines
    of code, and to be less declarative but more pythonic.
"""

import ast
from collections import defaultdict
from dis import dis, opmap, HAVE_ARGUMENT
from types import CodeType, FunctionType

class Opcodes: pass
op = Opcodes()
def take_arg(opcode):
    return lambda arg: bytes((opcode, arg % 256, arg // 256))
for name, opcode in opmap.items():
    setattr(op, name,
            bytes((opcode,)) if opcode < HAVE_ARGUMENT else take_arg(opcode))
op.JUMP_BACK = take_arg(255)    # A fake opcode for our internal use.

def bytecomp(node, f_globals):
    return FunctionType(CodeGen().compile(node), f_globals)

class CodeGen(ast.NodeVisitor):

    def __init__(self):
        self.constants = make_table()
        self.names     = make_table()
        self.varnames  = make_table()

    of = ast.NodeVisitor.visit

    def compile(self, t):
        bytecode = (self.of(t)
                    + op.LOAD_CONST(self.constants[None]) + op.RETURN_VALUE)
        argcount = 0
        kwonlyargcount = 0
        nlocals = 0
        stacksize = 10          # XXX
        flags = 67
        filename = '<stdin>'
        name = 'the_name'
        firstlineno = 1
        lnotab = b''
        return CodeType(argcount, kwonlyargcount, nlocals, stacksize, flags,
                        fix_jumps(bytecode),
                        collect(self.constants),
                        collect(self.names),
                        collect(self.varnames),
                        filename, name, firstlineno, lnotab,
                        freevars=(), cellvars=())

    def visits(self, nodes):
        return b''.join(map(self.of, nodes))

    def visit_Module(self, t):
        return self.visits(t.body)

    def visit_If(self, t):
        orelse = self.visits(t.orelse)
        body = self.visits(t.body) + op.JUMP_FORWARD(len(orelse))
        return self.of(t.test) + op.POP_JUMP_IF_FALSE(len(body)) + body + orelse

    def visit_While(self, t):
        test, body = self.of(t.test), self.visits(t.body)
        branch = op.POP_JUMP_IF_FALSE(len(body)+3)
        inside = test + branch + body
        loop = inside + op.JUMP_BACK(len(inside))
        return op.SETUP_LOOP(len(loop)) + loop + op.POP_BLOCK

    def visit_Expr(self, t):
        return self.of(t.value) + op.POP_TOP

    def visit_Assign(self, t):
        assert 1 == len(t.targets) and isinstance(t.targets[0], ast.Name)
        name = self.names[t.targets[0].id]
        return self.of(t.value) + op.DUP_TOP + op.STORE_GLOBAL(name)

    def visit_Call(self, t):
        return self.of(t.func) + self.visits(t.args) + op.CALL_FUNCTION(len(t.args))

    def visit_BinOp(self, t):
        return self.of(t.left) + self.of(t.right) + self.ops2[type(t.op)]
    ops2 = {ast.Add:    op.BINARY_ADD,      ast.Sub:      op.BINARY_SUBTRACT,
            ast.Mult:   op.BINARY_MULTIPLY, ast.Div:      op.BINARY_TRUE_DIVIDE,
            ast.Mod:    op.BINARY_MODULO,   ast.Pow:      op.BINARY_POWER,
            ast.LShift: op.BINARY_LSHIFT,   ast.RShift:   op.BINARY_RSHIFT,
            ast.BitOr:  op.BINARY_OR,       ast.BitXor:   op.BINARY_XOR,
            ast.BitAnd: op.BINARY_AND,      ast.FloorDiv: op.BINARY_FLOOR_DIVIDE}

    def visit_Num(self, t):
        return op.LOAD_CONST(self.constants[t.n])

    def visit_Name(self, t):
        return op.LOAD_GLOBAL(self.names[t.id])  # XXX LOAD_NAME in general

def fix_jumps(bytecode):
    i, result = 0, list(bytecode)
    while i < len(bytecode):
        opcode = bytecode[i]
        if opcode == opmap['POP_JUMP_IF_FALSE']:
            target = i + 3 + bytecode[i+1] + 256 * bytecode[i+2]
            result[i+1], result[i+2] = target % 256, target // 256
        elif opcode == 255:   # op.JUMP_BACK
            target = i - (bytecode[i+1] + 256 * bytecode[i+2])
            result[i] = opmap['JUMP_ABSOLUTE']
            result[i+1], result[i+2] = target % 256, target // 256
        i += 1 if opcode < HAVE_ARGUMENT else 3
    return bytes(result)

def make_table():
    table = defaultdict(lambda: len(table))
    return table

def collect(table):
    return tuple(sorted(table, key=table.get))


if __name__ == '__main__':
    eg_ast = ast.parse("""
a = 2+3
while a:
    if a - 1:
        print(a, 137)
    a = a - 1
print(pow(2, 16))
""")
    try:
        import astpp
    except ImportError:
        astpp = ast
    print(astpp.dump(eg_ast))
    f = bytecomp(eg_ast, globals())
    dis(f)
    f()   # It's alive!
