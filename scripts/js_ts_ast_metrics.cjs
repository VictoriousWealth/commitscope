const fs = require("fs");
const babelParser = require("@babel/parser");
const { Project, Node, SyntaxKind } = require("ts-morph");

const ARG_SEPARATOR = "\x1f";
const language = process.argv[2];
const relativePath = process.argv[3];
const knownClassNames = new Set((process.argv[4] || "").split(ARG_SEPARATOR).filter(Boolean));
const source = fs.readFileSync(0, "utf8");

function output(classes) {
  process.stdout.write(JSON.stringify(classes));
}

function walkBabel(node, visit) {
  if (!node || typeof node !== "object") {
    return;
  }
  visit(node);
  for (const [key, value] of Object.entries(node)) {
    if (key === "loc" || key === "start" || key === "end") {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        walkBabel(item, visit);
      }
      continue;
    }
    walkBabel(value, visit);
  }
}

function complexityFromText(bodyText, nodes, kindAccessor) {
  const branchKinds = new Set([
    "IfStatement",
    "ForStatement",
    "ForInStatement",
    "ForOfStatement",
    "WhileStatement",
    "DoWhileStatement",
    "SwitchCase",
    "ConditionalExpression",
    "CatchClause",
  ]);
  let cc = 1;
  for (const node of nodes) {
    if (branchKinds.has(kindAccessor(node))) {
      cc += 1;
    }
  }
  const matches = bodyText.match(/&&|\|\|/g);
  return cc + (matches ? matches.length : 0);
}

function classRefsFromNames(names) {
  return Array.from(names, (name) => `${relativePath}.${name}`);
}

function methodPayload(className, methodName, snippet, bodyText, parameters, fanout, cc, instanceVars, directCalls, classRefs) {
  const lines = bodyText.split(/\r?\n/).filter((line) => line.trim());
  return {
    class_name: className,
    method_name: `${className}.${methodName}`,
    method_simple_name: methodName,
    language,
    body: snippet,
    loc: snippet ? snippet.split(/\r?\n/).length : 1,
    lloc: lines.length || 1,
    parameters,
    fanout,
    cc,
    instance_vars: Array.from(instanceVars).sort(),
    direct_calls: Array.from(directCalls).sort(),
    class_refs: Array.from(classRefs).sort(),
  };
}

function parseJavaScript() {
  const ast = babelParser.parse(source, {
    sourceType: "unambiguous",
    plugins: [
      "jsx",
      "classProperties",
      "classPrivateProperties",
      "classPrivateMethods",
      "decorators-legacy",
      "optionalChaining",
      "nullishCoalescingOperator",
      "topLevelAwait",
    ],
  });

  const classes = [];
  walkBabel(ast, (node) => {
    if (node.type !== "ClassDeclaration" || !node.id || !node.body) {
      return;
    }
    const qualified = `${relativePath}.${node.id.name}`;
    const methods = [];
    for (const member of node.body.body || []) {
      const payload = babelMemberToMethod(qualified, member);
      if (payload) {
        methods.push(payload);
      }
    }
    classes.push({ class_name: qualified, language, methods });
  });
  output(classes);
}

function babelMemberToMethod(qualifiedClassName, member) {
  const kind = member.type;
  let methodName = null;
  let params = [];
  let bodyNode = null;

  if (kind === "ClassMethod" || kind === "ClassPrivateMethod") {
    methodName = member.kind === "constructor" ? "constructor" : babelMethodName(member.key);
    params = member.params || [];
    bodyNode = member.body;
  } else if (kind === "ClassProperty" || kind === "ClassPrivateProperty") {
    if (!member.value || member.value.type !== "ArrowFunctionExpression") {
      return null;
    }
    methodName = babelMethodName(member.key);
    params = member.value.params || [];
    bodyNode = member.value.body;
  } else {
    return null;
  }

  if (!methodName || !bodyNode) {
    return null;
  }

  const snippet = source.slice(member.start, member.end);
  const bodyText = source.slice(bodyNode.start, bodyNode.end);
  const nodes = [];
  const directCalls = new Set();
  const instanceVars = new Set();
  const referencedClasses = new Set();
  let fanout = 0;

  walkBabel(bodyNode, (node) => {
    nodes.push(node);
    if (node.type === "CallExpression" || node.type === "OptionalCallExpression") {
      fanout += 1;
      const name = babelCallName(node.callee);
      if (name) {
        directCalls.add(name);
      }
    } else if (node.type === "MemberExpression" || node.type === "OptionalMemberExpression") {
      if (node.object && node.object.type === "ThisExpression") {
        const name = babelPropertyName(node.property);
        if (name) {
          instanceVars.add(name);
        }
      }
    } else if (node.type === "Identifier" && knownClassNames.has(node.name)) {
      referencedClasses.add(node.name);
    }
  });

  return methodPayload(
    qualifiedClassName,
    methodName,
    snippet,
    bodyText,
    params.length,
    fanout,
    complexityFromText(bodyText, nodes, (node) => node.type),
    instanceVars,
    directCalls,
    classRefsFromNames(referencedClasses),
  );
}

function babelMethodName(key) {
  if (!key) {
    return null;
  }
  if (key.type === "Identifier") {
    return key.name;
  }
  if (key.type === "PrivateName" && key.id) {
    return `#${key.id.name}`;
  }
  if (key.type === "StringLiteral") {
    return key.value;
  }
  return null;
}

function babelPropertyName(node) {
  if (!node) {
    return null;
  }
  if (node.type === "Identifier") {
    return node.name;
  }
  if (node.type === "PrivateName" && node.id) {
    return `#${node.id.name}`;
  }
  return null;
}

function babelCallName(callee) {
  if (!callee) {
    return null;
  }
  if (callee.type === "Identifier") {
    return callee.name;
  }
  if (callee.type === "MemberExpression" || callee.type === "OptionalMemberExpression") {
    return babelPropertyName(callee.property);
  }
  if (callee.type === "PrivateName" && callee.id) {
    return `#${callee.id.name}`;
  }
  return null;
}

function parseTypeScript() {
  const project = new Project({ useInMemoryFileSystem: true, skipAddingFilesFromTsConfig: true });
  const sourceFile = project.createSourceFile("file.ts", source, { overwrite: true });
  const classes = [];

  for (const classDecl of sourceFile.getDescendantsOfKind(SyntaxKind.ClassDeclaration)) {
    const className = classDecl.getName();
    if (!className) {
      continue;
    }
    const qualified = `${relativePath}.${className}`;
    const methods = [];
    for (const member of classDecl.getMembers()) {
      const payload = tsMemberToMethod(qualified, member);
      if (payload) {
        methods.push(payload);
      }
    }
    classes.push({ class_name: qualified, language, methods });
  }

  output(classes);
}

function tsMemberToMethod(qualifiedClassName, member) {
  let methodName = null;
  let params = [];
  let bodyNode = null;

  if (Node.isMethodDeclaration(member)) {
    methodName = member.getName();
    params = member.getParameters();
    bodyNode = member.getBody();
  } else if (Node.isConstructorDeclaration(member)) {
    methodName = "constructor";
    params = member.getParameters();
    bodyNode = member.getBody();
  } else if (Node.isPropertyDeclaration(member)) {
    const initializer = member.getInitializer();
    if (!initializer || !Node.isArrowFunction(initializer)) {
      return null;
    }
    methodName = member.getName();
    params = initializer.getParameters();
    bodyNode = initializer.getBody();
  } else {
    return null;
  }

  if (!methodName || !bodyNode) {
    return null;
  }

  const snippet = member.getText();
  const bodyText = bodyNode.getText();
  const directCalls = new Set();
  const instanceVars = new Set();
  const referencedClasses = new Set();
  let fanout = 0;

  for (const callExpr of bodyNode.getDescendantsOfKind(SyntaxKind.CallExpression)) {
    fanout += 1;
    const expression = callExpr.getExpression().getText();
    const match = expression.match(/#?[A-Za-z_]\w*$/);
    if (match) {
      directCalls.add(match[0]);
    }
  }
  for (const propExpr of bodyNode.getDescendantsOfKind(SyntaxKind.PropertyAccessExpression)) {
    if (propExpr.getExpression().getText() === "this") {
      instanceVars.add(propExpr.getName());
    }
  }
  for (const identifier of bodyNode.getDescendantsOfKind(SyntaxKind.Identifier)) {
    const text = identifier.getText();
    if (knownClassNames.has(text)) {
      referencedClasses.add(text);
    }
  }

  const nodes = bodyNode.getDescendants();
  return methodPayload(
    qualifiedClassName,
    methodName,
    snippet,
    bodyText,
    params.length,
    fanout,
    complexityFromText(bodyText, nodes, (node) => node.getKindName()),
    instanceVars,
    directCalls,
    classRefsFromNames(referencedClasses),
  );
}

if (language === "javascript") {
  parseJavaScript();
} else if (language === "typescript") {
  parseTypeScript();
} else {
  process.stdout.write("[]");
}
