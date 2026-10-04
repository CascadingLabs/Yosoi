use proc_macro_crate::{FoundCrate, crate_name};
use quote::quote;
use syn::{
    Attribute, Data, DeriveInput, Expr, Fields, FieldsNamed, Ident, LitStr, Type,
    ext::IdentExt as _, spanned::Spanned as _,
};

pub fn reject_generics(input: &DeriveInput) -> syn::Result<()> {
    if input.generics.params.is_empty() {
        Ok(())
    } else {
        Err(syn::Error::new(
            input.generics.span(),
            "generic Contract structs are not supported in the first slice",
        ))
    }
}

pub fn named_fields(data: Data, span: proc_macro2::Span) -> syn::Result<FieldsNamed> {
    let Data::Struct(data) = data else {
        return Err(syn::Error::new(span, "Contract supports only structs"));
    };
    let Fields::Named(fields) = data.fields else {
        return Err(syn::Error::new(span, "Contract requires named fields"));
    };
    if fields.named.is_empty() {
        Err(syn::Error::new(
            span,
            "Contract requires at least one field",
        ))
    } else {
        Ok(fields)
    }
}

pub struct ContractAttributes {
    pub id: LitStr,
    pub description: LitStr,
    pub root: Option<Expr>,
}

pub fn contract_attributes(
    attributes: &[Attribute],
    span: proc_macro2::Span,
) -> syn::Result<ContractAttributes> {
    let mut id = None;
    let mut description = None;
    let mut root = None;
    for attribute in attributes {
        if !attribute.path().is_ident("ys") {
            continue;
        }
        attribute.parse_nested_meta(|meta| {
            if meta.path.is_ident("id") {
                if id.is_some() {
                    return Err(meta.error("Contract ID is declared more than once"));
                }
                id = Some(meta.value()?.parse::<LitStr>()?);
                return Ok(());
            }
            if meta.path.is_ident("description") {
                if description.is_some() {
                    return Err(meta.error("Contract description is declared more than once"));
                }
                description = Some(meta.value()?.parse::<LitStr>()?);
                return Ok(());
            }
            if meta.path.is_ident("root") {
                if root.is_some() {
                    return Err(meta.error("Contract root locator is declared more than once"));
                }
                root = Some(meta.value()?.parse::<Expr>()?);
                return Ok(());
            }
            if meta.path.is_ident("page") || meta.path.is_ident("repeated") {
                return Err(meta.error(
                    "page/repeated flags are removed; a root locator implies repeated and no root implies page",
                ));
            }
            Err(meta.error("unsupported ys Contract attribute"))
        })?;
    }
    Ok(ContractAttributes {
        id: required_non_empty(
            id,
            span,
            "Contract requires a non-empty #[ys(id = \"...\")]",
        )?,
        description: required_non_empty(
            description,
            span,
            "Contract requires a non-empty description",
        )?,
        root,
    })
}

pub struct FieldAttributes {
    pub id: LitStr,
    pub description: LitStr,
    pub rust_name: LitStr,
    pub locator: Option<Expr>,
}

pub fn field_attributes(
    attributes: &[Attribute],
    field_name: &Ident,
) -> syn::Result<FieldAttributes> {
    let semantic_name = field_name.unraw().to_string();
    if matches!(semantic_name.as_str(), "__document_id" | "__region") {
        return Err(syn::Error::new(
            field_name.span(),
            "Contract field name is reserved for generated candidate metadata",
        ));
    }
    let mut id = None;
    let mut description = None;
    let mut locator = None;
    for attribute in attributes {
        if !attribute.path().is_ident("ys") {
            continue;
        }
        attribute.parse_nested_meta(|meta| {
            if meta.path.is_ident("id") {
                if id.is_some() {
                    return Err(meta.error("field ID is declared more than once"));
                }
                id = Some(meta.value()?.parse::<LitStr>()?);
                return Ok(());
            }
            if meta.path.is_ident("description") {
                if description.is_some() {
                    return Err(meta.error("field description is declared more than once"));
                }
                description = Some(meta.value()?.parse::<LitStr>()?);
                return Ok(());
            }
            if meta.path.is_ident("locator") {
                if locator.is_some() {
                    return Err(meta.error("field locator is declared more than once"));
                }
                locator = Some(meta.value()?.parse::<Expr>()?);
                return Ok(());
            }
            Err(meta.error("unsupported ys field attribute"))
        })?;
    }
    let id = id.unwrap_or_else(|| LitStr::new(&semantic_name, field_name.span()));
    if id.value().trim().is_empty() {
        return Err(syn::Error::new(id.span(), "field ID cannot be empty"));
    }
    Ok(FieldAttributes {
        id,
        description: required_non_empty(
            description,
            field_name.span(),
            "Contract field requires a non-empty description",
        )?,
        rust_name: LitStr::new(&semantic_name, field_name.span()),
        locator,
    })
}

pub fn required_non_empty(
    value: Option<LitStr>,
    span: proc_macro2::Span,
    message: &str,
) -> syn::Result<LitStr> {
    let value = value.ok_or_else(|| syn::Error::new(span, message))?;
    if value.value().trim().is_empty() {
        Err(syn::Error::new(value.span(), message))
    } else {
        Ok(value)
    }
}

pub struct FieldShape {
    pub cardinality: proc_macro2::TokenStream,
    pub value_type: Type,
    pub reader: ReaderKind,
}

pub enum ReaderKind {
    Required,
    Optional,
    Many,
}

pub fn field_shape(field_type: &Type, yosoi: &proc_macro2::TokenStream) -> syn::Result<FieldShape> {
    if let Some(inner) = standard_wrapper_inner(field_type, "Option") {
        reject_nested_cardinality(inner)?;
        return Ok(FieldShape {
            cardinality: quote!(#yosoi::Cardinality::ZeroOrOne),
            value_type: inner.clone(),
            reader: ReaderKind::Optional,
        });
    }
    if let Some(inner) = standard_wrapper_inner(field_type, "Vec") {
        reject_nested_cardinality(inner)?;
        return Ok(FieldShape {
            cardinality: quote!(#yosoi::Cardinality::Many),
            value_type: inner.clone(),
            reader: ReaderKind::Many,
        });
    }
    if !matches!(field_type, Type::Path(_)) {
        return Err(syn::Error::new(
            field_type.span(),
            "Contract field must use a named Rust type",
        ));
    }
    Ok(FieldShape {
        cardinality: quote!(#yosoi::Cardinality::ExactlyOne),
        value_type: field_type.clone(),
        reader: ReaderKind::Required,
    })
}

fn reject_nested_cardinality(field_type: &Type) -> syn::Result<()> {
    if standard_wrapper_inner(field_type, "Option").is_some()
        || standard_wrapper_inner(field_type, "Vec").is_some()
    {
        Err(syn::Error::new(
            field_type.span(),
            "nested Option/Vec cardinality is not supported in the first Contract slice",
        ))
    } else {
        Ok(())
    }
}

fn standard_wrapper_inner<'a>(field_type: &'a Type, wrapper: &str) -> Option<&'a Type> {
    let Type::Path(path) = field_type else {
        return None;
    };
    let segments = &path.path.segments;
    let standard_path = match segments.len() {
        1 => true,
        3 => {
            let mut iter = segments.iter();
            matches!(
                iter.next()
                    .map(|segment| segment.ident.to_string())
                    .as_deref(),
                Some("std" | "core")
            ) && matches!(
                iter.next()
                    .map(|segment| segment.ident.to_string())
                    .as_deref(),
                Some("option" | "vec")
            )
        }
        _ => false,
    };
    if !standard_path {
        return None;
    }
    let segment = path.path.segments.last()?;
    if segment.ident != wrapper {
        return None;
    }
    let syn::PathArguments::AngleBracketed(arguments) = &segment.arguments else {
        return None;
    };
    if arguments.args.len() != 1 {
        return None;
    }
    let argument = arguments.args.first()?;
    let syn::GenericArgument::Type(inner) = argument else {
        return None;
    };
    Some(inner)
}

pub fn yosoi_path() -> syn::Result<proc_macro2::TokenStream> {
    for package in ["yosoi", "yosoi-engine"] {
        let resolved = match crate_name(package) {
            Ok(FoundCrate::Itself) => {
                let name = package.replace('-', "_");
                syn::Ident::new(&name, proc_macro2::Span::call_site())
            }
            Ok(FoundCrate::Name(name)) => {
                let name = name.replace('-', "_");
                syn::Ident::new(&name, proc_macro2::Span::call_site())
            }
            Err(_) => continue,
        };
        return if package == "yosoi" {
            Ok(quote!(::#resolved::__macro))
        } else {
            Ok(quote!(::#resolved))
        };
    }
    Err(syn::Error::new(
        proc_macro2::Span::call_site(),
        "Contract derive requires the yosoi package (or the internal yosoi-engine crate)",
    ))
}
