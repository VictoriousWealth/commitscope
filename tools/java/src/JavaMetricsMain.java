import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.BinaryExpr;
import com.github.javaparser.ast.expr.ConditionalExpr;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.ThisExpr;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.DoStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.SwitchEntry;
import com.github.javaparser.ast.stmt.WhileStmt;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class JavaMetricsMain {
    private static final String ARG_SEPARATOR = "\u001f";

    public static void main(String[] args) throws Exception {
        String relativePath = args.length > 0 ? args[0] : "";
        Set<String> knownClassNames = new HashSet<>();
        if (args.length > 1 && !args[1].isBlank()) {
            for (String name : args[1].split(ARG_SEPARATOR)) {
                if (!name.isBlank()) {
                    knownClassNames.add(name);
                }
            }
        }
        String source = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        CompilationUnit compilationUnit = StaticJavaParser.parse(source);
        List<String> lines = source.lines().toList();
        StringBuilder output = new StringBuilder("[");
        boolean firstClass = true;
        for (ClassOrInterfaceDeclaration declaration : compilationUnit.findAll(ClassOrInterfaceDeclaration.class)) {
            if (!firstClass) {
                output.append(",");
            }
            firstClass = false;
            String qualifiedClassName = relativePath + "." + declaration.getNameAsString();
            output.append("{");
            output.append("\"class_name\":\"").append(escape(qualifiedClassName)).append("\",");
            output.append("\"language\":\"java\",");
            output.append("\"methods\":[");
            boolean firstMethod = true;
            for (ConstructorDeclaration constructor : declaration.getConstructors()) {
                if (!firstMethod) {
                    output.append(",");
                }
                firstMethod = false;
                output.append(renderMethod(lines, relativePath, qualifiedClassName, constructor.getNameAsString(), constructor, constructor, knownClassNames));
            }
            for (MethodDeclaration method : declaration.getMethods()) {
                if (!firstMethod) {
                    output.append(",");
                }
                firstMethod = false;
                output.append(renderMethod(lines, relativePath, qualifiedClassName, method.getNameAsString(), method, method, knownClassNames));
            }
            output.append("]}");
        }
        output.append("]");
        System.out.print(output);
    }

    private static String renderMethod(
        List<String> lines,
        String relativePath,
        String qualifiedClassName,
        String methodSimpleName,
        com.github.javaparser.ast.Node rangeNode,
        com.github.javaparser.ast.Node traversalNode,
        Set<String> knownClassNames
    ) {
        String snippet = snippetFor(lines, rangeNode);
        String bodyText = snippet;
        int parameters = 0;
        if (traversalNode instanceof MethodDeclaration method) {
            parameters = method.getParameters().size();
        } else if (traversalNode instanceof ConstructorDeclaration constructor) {
            parameters = constructor.getParameters().size();
        }

        Set<String> instanceVars = new HashSet<>();
        for (FieldAccessExpr expr : traversalNode.findAll(FieldAccessExpr.class)) {
            if (expr.getScope() instanceof ThisExpr) {
                instanceVars.add(expr.getNameAsString());
            }
        }

        Set<String> directCalls = new HashSet<>();
        int fanout = 0;
        for (MethodCallExpr expr : traversalNode.findAll(MethodCallExpr.class)) {
            fanout += 1;
            directCalls.add(expr.getNameAsString());
        }

        Set<String> classRefs = new HashSet<>();
        for (ClassOrInterfaceType type : traversalNode.findAll(ClassOrInterfaceType.class)) {
            String name = type.getNameAsString();
            if (knownClassNames.contains(name)) {
                classRefs.add(relativePath + "." + name);
            }
        }
        for (NameExpr expr : traversalNode.findAll(NameExpr.class)) {
            String name = expr.getNameAsString();
            if (knownClassNames.contains(name)) {
                classRefs.add(relativePath + "." + name);
            }
        }

        int cc = 1;
        cc += traversalNode.findAll(IfStmt.class).size();
        cc += traversalNode.findAll(ForStmt.class).size();
        cc += traversalNode.findAll(ForEachStmt.class).size();
        cc += traversalNode.findAll(WhileStmt.class).size();
        cc += traversalNode.findAll(DoStmt.class).size();
        cc += traversalNode.findAll(SwitchEntry.class).size();
        cc += traversalNode.findAll(CatchClause.class).size();
        cc += traversalNode.findAll(ConditionalExpr.class).size();
        for (BinaryExpr expr : traversalNode.findAll(BinaryExpr.class)) {
            if (expr.getOperator() == BinaryExpr.Operator.AND || expr.getOperator() == BinaryExpr.Operator.OR) {
                cc += 1;
            }
        }

        int loc = snippet.isBlank() ? 1 : snippet.split("\\R", -1).length;
        int lloc = 0;
        for (String line : snippet.split("\\R")) {
            if (!line.trim().isEmpty()) {
                lloc += 1;
            }
        }
        if (lloc == 0) {
            lloc = 1;
        }

        return "{"
            + "\"class_name\":\"" + escape(qualifiedClassName) + "\","
            + "\"method_name\":\"" + escape(qualifiedClassName + "." + methodSimpleName) + "\","
            + "\"method_simple_name\":\"" + escape(methodSimpleName) + "\","
            + "\"language\":\"java\","
            + "\"body\":\"" + escape(bodyText) + "\","
            + "\"loc\":" + loc + ","
            + "\"lloc\":" + lloc + ","
            + "\"parameters\":" + parameters + ","
            + "\"fanout\":" + fanout + ","
            + "\"cc\":" + cc + ","
            + "\"instance_vars\":" + renderArray(new ArrayList<>(instanceVars)) + ","
            + "\"direct_calls\":" + renderArray(new ArrayList<>(directCalls)) + ","
            + "\"class_refs\":" + renderArray(new ArrayList<>(classRefs))
            + "}";
    }

    private static String snippetFor(List<String> lines, com.github.javaparser.ast.Node node) {
        if (node.getRange().isEmpty()) {
            return "";
        }
        int begin = Math.max(node.getRange().get().begin.line - 1, 0);
        int end = Math.min(node.getRange().get().end.line - 1, lines.size() - 1);
        StringBuilder builder = new StringBuilder();
        for (int index = begin; index <= end; index++) {
            if (index > begin) {
                builder.append("\n");
            }
            builder.append(lines.get(index));
        }
        return builder.toString();
    }

    private static String renderArray(List<String> values) {
        StringBuilder builder = new StringBuilder("[");
        boolean first = true;
        for (String value : values) {
            if (!first) {
                builder.append(",");
            }
            first = false;
            builder.append("\"").append(escape(value)).append("\"");
        }
        builder.append("]");
        return builder.toString();
    }

    private static String escape(String value) {
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t");
    }
}
