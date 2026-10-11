async function runYosoiModuleBundle(bundle, retainedBytes) {
  const NativeError = Error;
  const NativeObject = Object;
  const NativeArray = Array;
  const NativeNumber = Number;
  const NativeString = String;
  const NativeWeakSet = WeakSet;
  const nativeApply = Reflect.apply;
  const nativeArrayIsArray = Array.isArray;
  const nativeGetPrototypeOf = Object.getPrototypeOf;
  const nativeGetOwnPropertyDescriptor = Object.getOwnPropertyDescriptor;
  const nativeHasOwnProperty = Object.prototype.hasOwnProperty;
  const nativeNumberIsFinite = Number.isFinite;
  const nativeNumberIsSafeInteger = Number.isSafeInteger;
  const nativeJsonStringify = JSON.stringify;
  const nativeWeakSetHas = WeakSet.prototype.has;
  const nativeWeakSetAdd = WeakSet.prototype.add;
  const nativeWeakSetDelete = WeakSet.prototype.delete;
  const objectPrototype = Object.prototype;
  const arrayPrototype = Array.prototype;

  const MAX_JSON_NODES = 16384;
  const MAX_JSON_DEPTH = 128;
  const MAX_JSON_TEXT_CODE_UNITS = 1048576;
  const call = (fn, receiver, args) => nativeApply(fn, receiver, args);
  const hasOwn = (target, key) => call(nativeHasOwnProperty, target, [key]);
  const ownDescriptor = (target, key) =>
    call(nativeGetOwnPropertyDescriptor, NativeObject, [target, key]);
  const isDataDescriptor = (descriptor) =>
    descriptor !== undefined &&
    descriptor !== null &&
    hasOwn(descriptor, "value") &&
    !hasOwn(descriptor, "get") &&
    !hasOwn(descriptor, "set");
  const rejectsCallableOrAccessor = (descriptor) =>
    descriptor !== undefined &&
    descriptor !== null &&
    (!isDataDescriptor(descriptor) || typeof descriptor.value === "function");
  const rejectExport = (reason) => {
    throw new NativeError(`JavaScript module export is not JSON-compatible: ${reason}`);
  };

  const validateJsonExport = (root) => {
    const ancestors = new NativeWeakSet();
    const stack = [{ value: root, depth: 0, exit: false }];
    let stackLength = 1;
    let scheduledNodes = 1;
    let visitedNodes = 0;
    let textCodeUnits = 0;

    const addText = (value) => {
      if (value.length > MAX_JSON_TEXT_CODE_UNITS - textCodeUnits) {
        rejectExport("string data exceeds the validation bound");
      }
      textCodeUnits += value.length;
    };
    const schedule = (value, depth) => {
      if (scheduledNodes >= MAX_JSON_NODES) {
        rejectExport("value exceeds the node bound");
      }
      scheduledNodes += 1;
      stack[stackLength] = { value, depth, exit: false };
      stackLength += 1;
    };

    while (stackLength > 0) {
      const frame = stack[stackLength - 1];
      stackLength -= 1;
      if (frame.exit) {
        call(nativeWeakSetDelete, ancestors, [frame.value]);
        continue;
      }
      visitedNodes += 1;
      if (visitedNodes > MAX_JSON_NODES || frame.depth > MAX_JSON_DEPTH) {
        rejectExport("value exceeds the traversal bound");
      }

      const value = frame.value;
      if (value === null) {
        continue;
      }
      const valueType = typeof value;
      if (valueType === "string") {
        addText(value);
        continue;
      }
      if (valueType === "boolean") {
        continue;
      }
      if (valueType === "number") {
        if (!call(nativeNumberIsFinite, NativeNumber, [value])) {
          rejectExport("non-finite number");
        }
        continue;
      }
      if (valueType !== "object") {
        rejectExport(`unsupported ${valueType} value`);
      }
      if (call(nativeWeakSetHas, ancestors, [value])) {
        rejectExport("cyclic object graph");
      }

      const isArray = call(nativeArrayIsArray, NativeArray, [value]);
      const prototype = call(nativeGetPrototypeOf, NativeObject, [value]);
      if (
        value === objectPrototype ||
        value === arrayPrototype ||
        call(nativeGetPrototypeOf, NativeObject, [objectPrototype]) !== null ||
        call(nativeGetPrototypeOf, NativeObject, [arrayPrototype]) !== objectPrototype ||
        (isArray
          ? prototype !== arrayPrototype
          : prototype !== null && prototype !== objectPrototype)
      ) {
        rejectExport("non-plain object");
      }

      const ownToJson = ownDescriptor(value, "toJSON");
      const ownThen = ownDescriptor(value, "then");
      if (rejectsCallableOrAccessor(ownToJson) || rejectsCallableOrAccessor(ownThen)) {
        rejectExport("callable or accessor serialization hook");
      }
      if (
        (prototype !== null &&
          (rejectsCallableOrAccessor(ownDescriptor(prototype, "toJSON")) ||
            rejectsCallableOrAccessor(ownDescriptor(prototype, "then")))) ||
        (isArray &&
          (rejectsCallableOrAccessor(ownDescriptor(objectPrototype, "toJSON")) ||
            rejectsCallableOrAccessor(ownDescriptor(objectPrototype, "then"))))
      ) {
        rejectExport("inherited callable or accessor serialization hook");
      }

      call(nativeWeakSetAdd, ancestors, [value]);
      stack[stackLength] = { value, exit: true };
      stackLength += 1;

      if (isArray) {
        const lengthDescriptor = ownDescriptor(value, "length");
        if (!isDataDescriptor(lengthDescriptor)) {
          rejectExport("array length is not a data property");
        }
        const length = lengthDescriptor.value;
        if (
          !call(nativeNumberIsSafeInteger, NativeNumber, [length]) ||
          length < 0 ||
          length > MAX_JSON_NODES - scheduledNodes
        ) {
          rejectExport("array exceeds the traversal bound");
        }
        let elementCount = 0;
        for (const key in value) {
          if (!hasOwn(value, key)) {
            rejectExport("inherited enumerable array property");
          }
          const index = NativeNumber(key);
          if (
            !call(nativeNumberIsSafeInteger, NativeNumber, [index]) ||
            index < 0 ||
            index >= length ||
            NativeString(index) !== key
          ) {
            rejectExport("array has an unsupported property");
          }
          const descriptor = ownDescriptor(value, key);
          if (!isDataDescriptor(descriptor) || !descriptor.enumerable) {
            rejectExport("array contains an accessor");
          }
          elementCount += 1;
          schedule(descriptor.value, frame.depth + 1);
        }
        if (elementCount !== length) {
          rejectExport("sparse array");
        }
      } else {
        for (const key in value) {
          if (!hasOwn(value, key)) {
            rejectExport("inherited enumerable object property");
          }
          addText(key);
          const descriptor = ownDescriptor(value, key);
          if (!isDataDescriptor(descriptor) || !descriptor.enumerable) {
            rejectExport("object contains an accessor");
          }
          schedule(descriptor.value, frame.depth + 1);
        }
      }
    }
  };

  const registryKey = Symbol.for("yosoi.javascript.module_registry.v1");
  let registry = globalThis[registryKey];
  if (registry === undefined) {
    registry = { bundles: 0, bytes: 0, urls: [] };
    Object.defineProperty(globalThis, registryKey, { value: registry });
  }
  if (
    !registry ||
    !Number.isSafeInteger(registry.bundles) ||
    !Number.isSafeInteger(registry.bytes) ||
    !Array.isArray(registry.urls) ||
    registry.bundles < 0 ||
    registry.bytes < 0 ||
    registry.bundles >= bundle.maximumRetainedBundles ||
    retainedBytes > bundle.maximumRetainedBytes ||
    registry.bytes > bundle.maximumRetainedBytes - retainedBytes
  ) {
    throw new NativeError("JavaScript module document capacity exhausted");
  }

  const objectUrls = Object.create(null);
  const createdUrls = [];
  let retained = false;
  try {
    for (const [moduleId, source] of Object.entries(bundle.modules)) {
      const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
      objectUrls[moduleId] = url;
      createdUrls.push(url);
    }

    const entryUrl = objectUrls[bundle.entry];
    if (typeof entryUrl !== "string") {
      throw new NativeError("JavaScript module bundle has no entry module");
    }
    const namespaceLoaderSource =
      `import * as namespace from ${nativeJsonStringify(bundle.entrySpecifier)}; export { namespace };`;
    const namespaceLoaderUrl = URL.createObjectURL(
      new Blob([namespaceLoaderSource], { type: "text/javascript" })
    );
    createdUrls.push(namespaceLoaderUrl);

    const importMap = Object.create(null);
    for (const [specifier, targetModule] of Object.entries(bundle.imports)) {
      const targetUrl = objectUrls[targetModule];
      if (typeof targetUrl !== "string") {
        throw new NativeError("JavaScript module bundle references a missing module");
      }
      importMap[specifier] = targetUrl;
    }
    importMap[bundle.entrySpecifier] = entryUrl;
    importMap[bundle.loaderSpecifier] = namespaceLoaderUrl;

    const script = document.createElement("script");
    script.type = "importmap";
    script.textContent = nativeJsonStringify({ imports: importMap });
    const parent = document.head || document.documentElement;
    if (!parent) {
      throw new NativeError("JavaScript module import map could not be installed");
    }
    parent.appendChild(script);
    script.remove();

    // Keep Blob URLs alive for deferred literal dynamic imports until this
    // document's execution context is destroyed.
    registry.urls.push(...createdUrls);
    registry.bundles += 1;
    registry.bytes += retainedBytes;
    retained = true;

    const namespaceLoader = await import(bundle.loaderSpecifier);
    const namespace = namespaceLoader.namespace;
    if (bundle.resultExport === null) {
      return null;
    }
    if (!hasOwn(namespace, bundle.resultExport)) {
      throw new NativeError("requested JavaScript module export was not found");
    }
    const result = namespace[bundle.resultExport];
    validateJsonExport(result);
    return result;
  } catch (error) {
    if (!retained) {
      for (const url of createdUrls) {
        URL.revokeObjectURL(url);
      }
    }
    throw error;
  }
}
