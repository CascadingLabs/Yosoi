//! Python exceptions correspond to public SDK input and operation failures.

use pyo3::{create_exception, exceptions::PyException, prelude::*};

create_exception!(_native, YosoiError, PyException);
create_exception!(_native, DocumentError, YosoiError);
create_exception!(_native, ParseError, YosoiError);
create_exception!(_native, LocatorError, YosoiError);
create_exception!(_native, PolicyError, YosoiError);
create_exception!(_native, ClosedResourceError, YosoiError);
create_exception!(_native, RequestError, YosoiError);
create_exception!(_native, MapError, YosoiError);
create_exception!(_native, SearchError, YosoiError);
create_exception!(_native, ContractError, YosoiError);

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add("YosoiError", py.get_type::<YosoiError>())?;
    module.add("DocumentError", py.get_type::<DocumentError>())?;
    module.add("ParseError", py.get_type::<ParseError>())?;
    module.add("LocatorError", py.get_type::<LocatorError>())?;
    module.add("PolicyError", py.get_type::<PolicyError>())?;
    module.add("ClosedResourceError", py.get_type::<ClosedResourceError>())?;
    module.add("RequestError", py.get_type::<RequestError>())?;
    module.add("MapError", py.get_type::<MapError>())?;
    module.add("SearchError", py.get_type::<SearchError>())?;
    module.add("ContractError", py.get_type::<ContractError>())
}
