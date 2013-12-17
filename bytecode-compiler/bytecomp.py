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

import ast, collections, dis, types

class Opcodes: pass
op = Opcodes()
def take_arg(opcode):
    return lambda arg: bytes((opcode, arg % 256, arg // 256))
for name, opcode in dis.opmap.items():
    setattr(op, name,
            bytes((opcode,)) if opcode < dis.HAVE_ARGUMENT else take_arg(opcode))
op.JUMP_BACK = take_arg(255)    # A fake opcode for our internal use.

def bytecomp(t, f_globals):
    return types.FunctionType(CodeGen().compile(t), f_globals)

class CodeGen(ast.NodeVisitor):

    def __init__(self):
        self.constants = make_table()
        self.names     = make_table()
        self.varnames  = make_table()

    def compile(self, t):
        bytecode = (self.of(t)
                    + op.LOAD_CONST(self.constants[None]) + op.RETURN_VALUE)
        argcount = 0
        kwonlyargcount = 0
        nlocals = 0
        stacksize = 10          # XXX
        flags = 2 # meaning: newlocals
        filename = '<stdin>'
        name = 'the_name'
        firstlineno = 1
        lnotab = b''
        return types.CodeType(argcount, kwonlyargcount, nlocals, stacksize, flags,
                              fix_jumps(bytecode),
                              collect(self.constants),
                              collect(self.names),
                              collect(self.varnames),
                              filename, name, firstlineno, lnotab,
                              freevars=(), cellvars=())

    def of(self, t):
        return self.visits(t) if isinstance(t, list) else self.visit(t)

    def visits(self, nodes):
        return b''.join(map(self.of, nodes))

    def load_const(self, constant):
        return op.LOAD_CONST(self.constants[constant])

    def store(self, name):
#XXX        return op.STORE_NAME(self.names[name])
        return op.STORE_GLOBAL(self.names[name])

    def visit_Module(self, t):
        return self.of(t.body)

    def visit_FunctionDef(self, t):
        assert not t.args.args
        assert not t.decorator_list
        code = CodeGen().compile(t.body)
        return self.load_const(code) + op.MAKE_FUNCTION(0) + self.store(t.name)

    def visit_If(self, t):
        orelse = self.of(t.orelse)
        body = self.of(t.body) + op.JUMP_FORWARD(len(orelse))
        return self.of(t.test) + op.POP_JUMP_IF_FALSE(len(body)) + body + orelse

    def visit_While(self, t):
        test, body = self.of(t.test), self.of(t.body)
        branch = op.POP_JUMP_IF_FALSE(len(body)+3)
        inside = test + branch + body
        loop = inside + op.JUMP_BACK(len(inside))
        return op.SETUP_LOOP(len(loop)) + loop + op.POP_BLOCK

    def visit_Expr(self, t):
        return self.of(t.value) + op.POP_TOP

    def visit_Assign(self, t):
        assert 1 == len(t.targets) and isinstance(t.targets[0], ast.Name)
        return self.of(t.value) + op.DUP_TOP + self.store(t.targets[0].id)

    def visit_Call(self, t):
        return self.of(t.func) + self.of(t.args) + op.CALL_FUNCTION(len(t.args))

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

    def visit_Str(self, t):
        return op.LOAD_CONST(self.constants[t.s])

    def visit_Name(self, t):
        return op.LOAD_GLOBAL(self.names[t.id])  # XXX LOAD_NAME in general

def fix_jumps(bytecode):
    i, result = 0, list(bytecode)
    while i < len(bytecode):
        opcode = bytecode[i]
        if opcode in dis.hasjabs:
            target = i + 3 + bytecode[i+1] + 256 * bytecode[i+2]
            result[i+1], result[i+2] = target % 256, target // 256
        elif opcode == 255:   # op.JUMP_BACK
            target = i - (bytecode[i+1] + 256 * bytecode[i+2])
            result[i] = dis.opmap['JUMP_ABSOLUTE']
            result[i+1], result[i+2] = target % 256, target // 256
        i += 1 if opcode < dis.HAVE_ARGUMENT else 3
    return bytes(result)

def make_table():
    table = collections.defaultdict(lambda: len(table))
    return table

def collect(table):
    return tuple(sorted(table, key=table.get))


if __name__ == '__main__':
    eg_ast = ast.parse("""
a = 2+3
def f():
    "doc comment"
    while a:
        if a - 1:
            print(a, 137)
        a = a - 1
f()
print(pow(2, 16))
""")
    try:
        import astpp
    except ImportError:
        astpp = ast
    print(astpp.dump(eg_ast))
    f = bytecomp(eg_ast, globals())
    dis.dis(f)
    f()   # It's alive!
