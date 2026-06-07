/**
 * @name Hard-coded selector in Yosoi example
 * @description Yosoi examples must define contracts and let selector discovery learn selectors.
 * @kind problem
 * @problem.severity error
 * @precision high
 * @id py/yosoi/hard-coded-example-selector
 * @tags maintainability
 */

import python

predicate inExamplePython(Expr e) {
  exists(string path |
    path = e.getLocation().getFile().getRelativePath() and
    path.matches("examples/%.py")
  )
}

predicate selectorKeyword(string name) {
  name = "selector" or
  name = "selectors" or
  name = "root_selector" or
  name = "row_selector"
}

predicate selectorFactoryName(string name) {
  name = "css" or name = "xpath"
}

predicate selectorishName(string name) {
  name.matches("%selector%") or
  name.matches("%selectors%") or
  name.matches("%root%") or
  name.matches("%xpath%") or
  name.matches("%css%")
}

predicate selectorLiteral(string value) {
  value.regexpFind("(^|[\\s,(])([.#][A-Za-z_-][A-Za-z0-9_-]*|[A-Za-z][A-Za-z0-9_-]*(\\[[^\\]]+\\]|[.#][A-Za-z_-][A-Za-z0-9_-]*)|//[A-Za-z*]|::(attr|text)\\b)")
}

predicate universalSelectorLiteral(string value) {
  value.regexpFind("(^|[\\s,(])([.#][A-Za-z_-][A-Za-z0-9_-]*|[A-Za-z][A-Za-z0-9_-]*\\[[^\\]]+\\]|//[A-Za-z*]|::(attr|text)\\b)")
}

predicate browserSelectorApi(string value) {
  value.indexOf("querySelector(") >= 0 or
  value.indexOf("querySelectorAll(") >= 0 or
  value.indexOf(".closest(") >= 0 or
  value.indexOf(".matches(") >= 0 or
  value.indexOf("XPathEvaluator") >= 0 or
  value.indexOf("document.evaluate(") >= 0
}

predicate selectorConstructionMarker(string value) {
  value.indexOf(".") >= 0 or
  value.indexOf("#") >= 0 or
  value.indexOf("//") >= 0 or
  value.indexOf("[") >= 0 or
  value.indexOf("::") >= 0
}

predicate exprContainsString(Expr container, StrConst literal) {
  container = literal or literal = container.getASubExpression+()
}

predicate hasSelectorFactoryCall(Call call) {
  exists(Name name |
    call.getFunc() = name and
    selectorFactoryName(name.getId())
  )
  or
  exists(Attribute attr |
    call.getFunc() = attr and
    selectorFactoryName(attr.getName())
  )
}

predicate hasBrowserSelectorCall(Call call) {
  exists(Attribute attr |
    call.getFunc() = attr and
    (
      attr.getName() = "querySelector" or
      attr.getName() = "querySelectorAll" or
      attr.getName() = "closest" or
      attr.getName() = "matches"
    )
  )
}

predicate selectorKeywordLiteral(StrConst literal) {
  exists(Call call, string name |
    inExamplePython(call) and
    selectorKeyword(name) and
    exprContainsString(call.getNamedArg(name), literal)
  )
}

predicate selectorishAssignmentLiteral(StrConst literal) {
  exists(Assign assign, Expr target, string targetName |
    inExamplePython(assign) and
    target = assign.getATarget() and
    (
      target instanceof Name and targetName = target.(Name).getId()
      or
      target instanceof Attribute and targetName = target.(Attribute).getName()
    ) and
    selectorishName(targetName) and
    exprContainsString(assign.getValue(), literal)
  )
}

predicate selectorishAssignmentComposed(Expr expr) {
  exists(Assign assign, Expr target, string targetName, BinaryExpr value |
    inExamplePython(assign) and
    target = assign.getATarget() and
    (
      target instanceof Name and targetName = target.(Name).getId()
      or
      target instanceof Attribute and targetName = target.(Attribute).getName()
    ) and
    selectorishName(targetName) and
    value = assign.getValue() and
    expr = value and
    exists(StrConst literal | exprContainsString(value, literal))
  )
}

predicate fstringSelectorConstruction(Fstring fstring) {
  exists(StrConst literal |
    literal = fstring.getAValue() and
    selectorConstructionMarker(literal.getText())
  )
}

from Expr result, string reason
where
  (
    exists(Call call |
      result = call and
      inExamplePython(call) and
      hasSelectorFactoryCall(call) and
      reason = "Yosoi examples must not call hard-coded selector factories."
    )
    or
    exists(Call call |
      result = call and
      inExamplePython(call) and
      hasBrowserSelectorCall(call) and
      reason = "Yosoi examples must not call browser selector APIs directly."
    )
    or
    exists(Fstring fstring |
      result = fstring and
      inExamplePython(fstring) and
      fstringSelectorConstruction(fstring) and
      reason = "Yosoi examples must not construct selectors with f-strings."
    )
    or
    exists(Expr expr |
      result = expr and
      selectorishAssignmentComposed(expr) and
      reason = "Yosoi examples must not construct selector-like names from composed strings."
    )
    or
    exists(StrConst literal, string value |
      result = literal and
      inExamplePython(literal) and
      value = literal.getText() and
      universalSelectorLiteral(value) and
      reason = "Yosoi examples must not contain hard-coded selector literals."
    )
    or
    exists(StrConst literal, string value |
      result = literal and
      inExamplePython(literal) and
      value = literal.getText() and
      browserSelectorApi(value) and
      reason = "Yosoi examples must not embed browser selector APIs in string literals."
    )
    or
    exists(StrConst literal, string value |
      result = literal and
      value = literal.getText() and
      selectorKeywordLiteral(literal) and
      (selectorLiteral(value) or browserSelectorApi(value)) and
      reason = "Yosoi examples must not pass selector literals through selector keyword arguments."
    )
    or
    exists(StrConst literal, string value |
      result = literal and
      value = literal.getText() and
      selectorishAssignmentLiteral(literal) and
      (selectorLiteral(value) or browserSelectorApi(value)) and
      reason = "Yosoi examples must not assign selector literals to selector-like names."
    )
  )
select result, reason
