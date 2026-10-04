use crate::support::{ReaderKind, field_attributes, field_shape};
use quote::{format_ident, quote};
use std::collections::BTreeSet;
use syn::{Field, Ident, spanned::Spanned as _};

pub struct ExpandedField {
    pub schema: proc_macro2::TokenStream,
    pub candidate_field: proc_macro2::TokenStream,
    pub candidate_initializer: proc_macro2::TokenStream,
    pub candidate_debug_entry: proc_macro2::TokenStream,
    pub validation_result: proc_macro2::TokenStream,
    pub issue_flag: proc_macro2::TokenStream,
    pub issue_move: proc_macro2::TokenStream,
    pub value_unwrap: proc_macro2::TokenStream,
    pub record_field: Ident,
    pub portable_record_field: proc_macro2::TokenStream,
    pub portable_record_decode: proc_macro2::TokenStream,
    pub portable_candidate_field: proc_macro2::TokenStream,
    pub value_count_step: proc_macro2::TokenStream,
    pub plan_locator: Option<proc_macro2::TokenStream>,
    pub locator_label: String,
}

pub fn expand_field(
    field: Field,
    yosoi: &proc_macro2::TokenStream,
    seen_ids: &mut BTreeSet<String>,
) -> syn::Result<ExpandedField> {
    let field_span = field.span();
    let field_name = field
        .ident
        .ok_or_else(|| syn::Error::new(field_span, "Contract requires named fields"))?;
    let field_visibility = field.vis;
    let attributes = field_attributes(&field.attrs, &field_name)?;
    let field_id = attributes.id;
    let field_description = attributes.description;
    let field_label = attributes.rust_name;
    let locator = attributes.locator;
    let authored_field_name = field_label.value();
    if !seen_ids.insert(field_id.value()) {
        return Err(syn::Error::new(
            field_id.span(),
            "field ID is declared more than once",
        ));
    }
    let field_type = field.ty.clone();
    let shape = field_shape(&field.ty, yosoi)?;
    let cardinality = shape.cardinality;
    let value_type = shape.value_type;
    let result_name = format_ident!("__ys_{}_result", authored_field_name);
    let reader = match shape.reader {
        ReaderKind::Required => quote!(#yosoi::read_required),
        ReaderKind::Optional => quote!(#yosoi::read_optional),
        ReaderKind::Many => quote!(#yosoi::read_many),
    };

    Ok(ExpandedField {
        schema: quote! {
            #yosoi::FieldSchema::from_derive(
                #field_id,
                #field_description,
                #cardinality,
                <#value_type as #yosoi::ContractValue>::TYPE_ID,
            )?
        },
        candidate_field: quote! {
            #field_visibility #field_name: #yosoi::CandidateField<#value_type>
        },
        candidate_initializer: quote! {
            #field_name: #yosoi::CandidateField::from_input(#field_id, input)
        },
        candidate_debug_entry: quote! {
            debug.field(#field_label, &self.#field_name);
        },
        validation_result: quote! {
            let #result_name = #reader(&candidate.#field_name);
        },
        issue_flag: quote! {
            #result_name.is_err()
        },
        issue_move: quote! {
            if let Err(issue) = #result_name {
                issues.push(issue);
            }
        },
        value_unwrap: quote! {
            let #field_name = match #result_name {
                Ok(value) => value,
                Err(issue) => return Err(vec![issue]),
            };
        },
        record_field: field_name.clone(),
        portable_record_field: quote! {
            #yosoi::__private::PortableContractFieldShape::to_portable_field(
                &self.#field_name,
                #yosoi::FieldId::from_derive(#field_id),
            )
        },
        portable_record_decode: quote! {
            let #field_name = {
                let field_id = #yosoi::FieldId::from_derive(#field_id);
                let portable = record
                    .fields()
                    .iter()
                    .find(|field| field.id() == &field_id)
                    .ok_or_else(|| #yosoi::__private::PortableContractDecodeError::MissingField {
                        field: field_id.clone(),
                    })?;
                <#field_type as #yosoi::__private::PortableContractFieldShape>::from_portable_field(
                    portable,
                )?
            };
        },
        portable_candidate_field: quote! {
            #yosoi::__private::PortableCandidateField::new(
                #yosoi::FieldId::from_derive(#field_id),
                candidate.#field_name.evidence().to_vec(),
            )
        },
        value_count_step: quote! {
            count = count.checked_add(u64::try_from(self.#field_name.len()).ok()?)?;
        },
        plan_locator: locator.map(|locator| quote!((#field_id, #locator))),
        locator_label: authored_field_name,
    })
}
