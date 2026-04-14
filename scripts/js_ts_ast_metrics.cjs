const fs = require("fs");
const path = require("path");
const babelParser = require("@babel/parser");
const { Project, Node, SyntaxKind } = require("ts-morph");

const ARG_SEPARATOR = "\x1f";
const CLASS_NAME_SEPARATOR = "\x1e";
const CLASS_LIST_SEPARATOR = "\x1d";
const language = process.argv[2];
const relativePath = process.argv[3];
const knownClasses = parseKnownClasses(process.argv[4] || "");
const knownClassNames = new Set(knownClasses.keys());
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
  return Array.from(names).sort();
}

function parseKnownClasses(raw) {
  const result = new Map();
  for (const entry of raw.split(ARG_SEPARATOR).filter(Boolean)) {
    const [className, qualifiedNamesRaw = ""] = entry.split(CLASS_NAME_SEPARATOR);
    result.set(className, qualifiedNamesRaw ? qualifiedNamesRaw.split(CLASS_LIST_SEPARATOR).filter(Boolean) : []);
  }
  return result;
}

function uniqueQualifiedClass(className) {
  const matches = knownClasses.get(className) || [];
  return matches.length === 1 ? matches[0] : null;
}

function buildQualifiedMethod(className, methodName) {
  const qualifiedClassName = uniqueQualifiedClass(className);
  return qualifiedClassName ? `${qualifiedClassName}.${methodName}` : null;
}

function qualifiedClassFromIdentifier(name, importedClasses = new Map()) {
  return importedClasses.get(name) || uniqueQualifiedClass(name);
}

function collectBabelImports(programNode) {
  const importedClasses = new Map();
  for (const node of programNode.body || []) {
    if (node.type !== "ImportDeclaration") {
      continue;
    }
    for (const specifier of node.specifiers || []) {
      if (
        specifier.type === "ImportSpecifier" ||
        specifier.type === "ImportDefaultSpecifier"
      ) {
        const importedName = specifier.imported ? specifier.imported.name : specifier.local.name;
        const qualifiedClassName = qualifiedClassFromIdentifier(importedName);
        if (qualifiedClassName) {
          importedClasses.set(specifier.local.name, qualifiedClassName);
        }
      }
    }
  }
  return importedClasses;
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

  const importedClasses = collectBabelImports(ast.program);
  const classes = [];
  walkBabel(ast, (node) => {
    if (node.type !== "ClassDeclaration" || !node.id || !node.body) {
      return;
    }
    const qualified = `${relativePath}.${node.id.name}`;
    const methods = [];
    for (const member of node.body.body || []) {
      const payload = babelMemberToMethod(qualified, member, importedClasses);
      if (payload) {
        methods.push(payload);
      }
    }
    classes.push({ class_name: qualified, language, methods });
  });
  output(classes);
}

function babelMemberToMethod(qualifiedClassName, member, importedClasses) {
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
  const localVarTypes = new Map();
  let fanout = 0;

  walkBabel(bodyNode, (node) => {
    nodes.push(node);
    if (node.type === "VariableDeclarator" && node.id && node.id.type === "Identifier") {
      const inferredType = babelInferClassName(node.init, importedClasses);
      if (inferredType) {
        localVarTypes.set(node.id.name, inferredType);
      }
    }
    if (node.type === "CallExpression" || node.type === "OptionalCallExpression") {
      fanout += 1;
      const name = resolveBabelCallTarget(node.callee, qualifiedClassName, localVarTypes, importedClasses);
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
      const qualifiedClassNameRef = qualifiedClassFromIdentifier(node.name, importedClasses);
      if (qualifiedClassNameRef) {
        referencedClasses.add(qualifiedClassNameRef);
      }
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

function babelInferClassName(node, importedClasses) {
  if (!node) {
    return null;
  }
  if (node.type === "NewExpression") {
    if (node.callee.type === "Identifier") {
      return node.callee.name;
    }
    if ((node.callee.type === "MemberExpression" || node.callee.type === "OptionalMemberExpression") && node.callee.property) {
      return babelPropertyName(node.callee.property);
    }
  }
  if (node.type === "Identifier") {
    const qualifiedClassName = qualifiedClassFromIdentifier(node.name, importedClasses);
    if (qualifiedClassName) {
      return node.name;
    }
  }
  return null;
}

function resolveBabelCallTarget(callee, qualifiedClassName, localVarTypes, importedClasses) {
  if (!callee) {
    return null;
  }
  if (callee.type === "Identifier") {
    return `${qualifiedClassName}.${callee.name}`;
  }
  if (callee.type === "MemberExpression" || callee.type === "OptionalMemberExpression") {
    const methodName = babelPropertyName(callee.property);
    if (!methodName) {
      return null;
    }
    if (callee.object && callee.object.type === "ThisExpression") {
      return `${qualifiedClassName}.${methodName}`;
    }
    if (callee.object && callee.object.type === "Identifier") {
      const inferredType = localVarTypes.get(callee.object.name);
      if (inferredType) {
        const qualifiedOwner = buildQualifiedMethod(inferredType, methodName);
        if (qualifiedOwner) {
          return qualifiedOwner;
        }
      }
      const qualifiedOwnerClass = qualifiedClassFromIdentifier(callee.object.name, importedClasses);
      if (qualifiedOwnerClass) {
        return `${qualifiedOwnerClass}.${methodName}`;
      }
    }
    const fallback = babelCallName(callee);
    return fallback ? fallback : null;
  }
  return babelCallName(callee);
}

function parseTypeScript() {
  const project = new Project({ useInMemoryFileSystem: true, skipAddingFilesFromTsConfig: true });
  const sourceFile = project.createSourceFile("file.ts", source, { overwrite: true });
  const classes = [];
  const importedClasses = collectTsImports(sourceFile);

  for (const classDecl of sourceFile.getDescendantsOfKind(SyntaxKind.ClassDeclaration)) {
    const className = classDecl.getName();
    if (!className) {
      continue;
    }
    const qualified = `${relativePath}.${className}`;
    const methods = [];
    for (const member of classDecl.getMembers()) {
      const payload = tsMemberToMethod(qualified, member, importedClasses);
      if (payload) {
        methods.push(payload);
      }
    }
    classes.push({ class_name: qualified, language, methods });
  }

  output(classes);
}

function tsMemberToMethod(qualifiedClassName, member, importedClasses) {
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
  const localVarTypes = new Map();
  let fanout = 0;

  for (const declaration of bodyNode.getDescendantsOfKind(SyntaxKind.VariableDeclaration)) {
    const nameNode = declaration.getNameNode();
    if (!Node.isIdentifier(nameNode)) {
      continue;
    }
    const inferredType = tsInferClassName(declaration, importedClasses);
    if (inferredType) {
      localVarTypes.set(nameNode.getText(), inferredType);
    }
  }
  for (const callExpr of bodyNode.getDescendantsOfKind(SyntaxKind.CallExpression)) {
    fanout += 1;
    const target = resolveTsCallTarget(callExpr.getExpression(), qualifiedClassName, localVarTypes, importedClasses);
    if (target) {
      directCalls.add(target);
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
      const qualifiedClassNameRef = qualifiedClassFromIdentifier(text, importedClasses);
      if (qualifiedClassNameRef) {
        referencedClasses.add(qualifiedClassNameRef);
      }
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

function collectTsImports(sourceFile) {
  const importedClasses = new Map();
  for (const importDecl of sourceFile.getImportDeclarations()) {
    const defaultImport = importDecl.getDefaultImport();
    if (defaultImport) {
      const qualifiedClassName = qualifiedClassFromIdentifier(defaultImport.getText());
      if (qualifiedClassName) {
        importedClasses.set(defaultImport.getText(), qualifiedClassName);
      }
    }
    for (const specifier of importDecl.getNamedImports()) {
      const importedName = specifier.getName();
      const qualifiedClassName = qualifiedClassFromIdentifier(importedName);
      if (qualifiedClassName) {
        importedClasses.set(specifier.getAliasNode()?.getText() || importedName, qualifiedClassName);
      }
    }
  }
  return importedClasses;
}

function tsInferClassName(declaration, importedClasses) {
  const initializer = declaration.getInitializer();
  if (initializer && Node.isNewExpression(initializer)) {
    const expression = initializer.getExpression();
    if (Node.isIdentifier(expression)) {
      return expression.getText();
    }
    if (Node.isPropertyAccessExpression(expression)) {
      return expression.getName();
    }
  }
  const typeNode = declaration.getTypeNode();
  if (typeNode && Node.isTypeReference(typeNode)) {
    const typeName = typeNode.getTypeName().getText();
    if (qualifiedClassFromIdentifier(typeName, importedClasses)) {
      return typeName;
    }
  }
  return null;
}

function resolveTsCallTarget(expression, qualifiedClassName, localVarTypes, importedClasses) {
  if (Node.isIdentifier(expression)) {
    return `${qualifiedClassName}.${expression.getText()}`;
  }
  if (Node.isPropertyAccessExpression(expression)) {
    const methodName = expression.getName();
    const owner = expression.getExpression().getText();
    if (owner === "this") {
      return `${qualifiedClassName}.${methodName}`;
    }
    const inferredType = localVarTypes.get(owner);
    if (inferredType) {
      const qualifiedOwner = buildQualifiedMethod(inferredType, methodName);
      if (qualifiedOwner) {
        return qualifiedOwner;
      }
    }
    const qualifiedOwnerClass = qualifiedClassFromIdentifier(owner, importedClasses);
    if (qualifiedOwnerClass) {
      return `${qualifiedOwnerClass}.${methodName}`;
    }
  }
  const match = expression.getText().match(/#?[A-Za-z_]\w*$/);
  return match ? match[0] : null;
}

if (language === "javascript") {
  parseJavaScript();
} else if (language === "typescript") {
  parseTypeScript();
} else {
  process.stdout.write("[]");
}
