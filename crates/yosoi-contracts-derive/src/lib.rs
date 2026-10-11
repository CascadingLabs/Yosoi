//! Derive macro for Yosoi Contract declarations.

mod field_expansion;
mod support;

use field_expansion::expand_field;
use proc_macro::TokenStream;
use quote::{format_ident, quote};
use std::collections::BTreeSet;
use support::{contract_attributes, named_fields, reject_generics, yosoi_path};
use syn::{DeriveInput, parse_macro_input};

#[proc_macro_derive(Contract, attributes(ys))]
pub fn derive_contract(input: TokenStream) -> TokenStream {
    match expand_contract(parse_macro_input!(input as DeriveInput)) {
        Ok(tokens) => tokens.into(),
        Err(error) => error.into_compile_error().into(),
    }
}

#[allow(clippy::cognitive_complexity)] // Generated validation control flow lives inside quote!.
fn expand_contract(input: DeriveInput) -> syn::Result<proc_macro2::TokenStream> {
    reject_generics(&input)?;
    let attributes = contract_attributes(&input.attrs, input.ident.span())?;
    let yosoi = yosoi_path(attributes.crate_path.as_ref())?;
    let type_name = input.ident;
    let visibility = input.vis;
    let candidate_name = format_ident!("{type_name}Candidate");
    let extracted_name = format_ident!("{type_name}Extracted");
    let contract_id = attributes.id;
    let description = attributes.description;
    let root = attributes.root;
    let scope = if root.is_some() {
        quote!(#yosoi::RecordScope::Repeated)
    } else {
        quote!(#yosoi::RecordScope::Page)
    };
    let root_locator = root.map_or_else(|| quote!(None), |root| quote!(Some(#root)));

    let fields = named_fields(input.data, type_name.span())?;
    let field_count = fields.named.len();

    let mut seen_ids = BTreeSet::new();
    let mut schemas = Vec::new();
    let mut candidate_fields = Vec::new();
    let mut candidate_initializers = Vec::new();
    let mut candidate_debug_entries = Vec::new();
    let mut validation_results = Vec::new();
    let mut issue_flags = Vec::new();
    let mut issue_moves = Vec::new();
    let mut value_unwraps = Vec::new();
    let mut record_fields = Vec::new();
    let mut portable_record_fields = Vec::new();
    let mut portable_record_decodes = Vec::new();
    let mut portable_candidate_fields = Vec::new();
    let mut value_count_steps = Vec::new();
    let mut plan_locators = Vec::new();
    let mut locator_labels = Vec::new();

    for field in fields.named {
        let field = expand_field(field, &yosoi, &mut seen_ids)?;
        schemas.push(field.schema);
        candidate_fields.push(field.candidate_field);
        candidate_initializers.push(field.candidate_initializer);
        candidate_debug_entries.push(field.candidate_debug_entry);
        validation_results.push(field.validation_result);
        issue_flags.push(field.issue_flag);
        issue_moves.push(field.issue_move);
        value_unwraps.push(field.value_unwrap);
        record_fields.push(field.record_field);
        portable_record_fields.push(field.portable_record_field);
        portable_record_decodes.push(field.portable_record_decode);
        portable_candidate_fields.push(field.portable_candidate_field);
        value_count_steps.push(field.value_count_step);
        plan_locators.push(field.plan_locator);
        locator_labels.push(field.locator_label);
    }

    let pinned_field_count = plan_locators
        .iter()
        .filter(|locator| locator.is_some())
        .count();
    if pinned_field_count != 0 && pinned_field_count != field_count {
        let missing = locator_labels
            .iter()
            .zip(&plan_locators)
            .filter(|(_, locator)| locator.is_none())
            .map(|(label, _)| label.as_str())
            .collect::<Vec<_>>()
            .join(", ");
        return Err(syn::Error::new(
            type_name.span(),
            format!("a located Contract must pin every field; missing locators: {missing}"),
        ));
    }
    let plan_methods = if pinned_field_count == field_count {
        let plan_locators = plan_locators.into_iter().flatten();
        quote! {
            const __YS_FIELD_LOCATORS: &'static [
                (&'static str, #yosoi::PinnedOutputLocator)
            ] = &[#(#plan_locators),*];

            pub fn plan() -> Result<&'static #yosoi::Plan, #yosoi::ContractLocatorError> {
                static PLAN: ::std::sync::OnceLock<
                    Result<#yosoi::Plan, #yosoi::ContractLocatorError>
                > = ::std::sync::OnceLock::new();
                PLAN.get_or_init(|| #yosoi::compile_contract_plan(
                    #contract_id,
                    Self::root_locator(),
                    Self::__YS_FIELD_LOCATORS,
                )).as_ref().map_err(Clone::clone)
            }

            pub fn locate(
                document: &#yosoi::Document,
            ) -> Result<#yosoi::LocateOutcome, #yosoi::ContractLocatorError> {
                Ok(document.locate(Self::plan()?))
            }
        }
    } else {
        quote! {}
    };

    Ok(quote! {
        #[derive(Clone)]
        #visibility struct #candidate_name {
            __document_id: #yosoi::DocumentId,
            __region: Option<#yosoi::RegionLineage>,
            #(#candidate_fields),*
        }

        impl ::std::fmt::Debug for #candidate_name {
            fn fmt(
                &self,
                formatter: &mut ::std::fmt::Formatter<'_>,
            ) -> ::std::fmt::Result {
                let mut debug = formatter.debug_struct(stringify!(#candidate_name));
                #(#candidate_debug_entries)*
                debug.finish_non_exhaustive()
            }
        }

        impl #yosoi::CandidateView for #candidate_name {
            fn document_id(&self) -> &#yosoi::DocumentId {
                &self.__document_id
            }

            fn region(&self) -> Option<&#yosoi::RegionLineage> {
                self.__region.as_ref()
            }

            fn value_count(&self) -> Option<u64> {
                let mut count = 0_u64;
                #(#value_count_steps)*
                Some(count)
            }
        }

        impl #yosoi::Contract for #type_name {
            type Candidate = #candidate_name;
            type Extracted = #extracted_name;

            fn schema() -> Result<&'static #yosoi::ContractSchema, #yosoi::ContractSchemaError> {
                static SCHEMA: ::std::sync::OnceLock<
                    Result<#yosoi::ContractSchema, #yosoi::ContractSchemaError>
                > =
                    ::std::sync::OnceLock::new();
                SCHEMA.get_or_init(|| #yosoi::ContractSchema::from_derive(
                    #contract_id,
                    #description,
                    #scope,
                    vec![#(#schemas),*],
                )).as_ref().map_err(Clone::clone)
            }

            fn candidate_from(input: &#yosoi::CandidateInput) -> Self::Candidate {
                #candidate_name {
                    __document_id: input.document_id().clone(),
                    __region: input.region().cloned(),
                    #(#candidate_initializers),*
                }
            }
        }

        impl #yosoi::ArchivedContract for #type_name {
            fn to_archived_record(
                &self,
                candidate: &Self::Candidate,
            ) -> #yosoi::__private::PortableValidatedContractRecord {
                #yosoi::__private::PortableValidatedContractRecord::new(
                    #yosoi::CandidateView::document_id(candidate).clone(),
                    #yosoi::CandidateView::region(candidate).cloned(),
                    vec![#(#portable_record_fields),*],
                    Self::to_archived_candidate(candidate),
                )
            }

            fn to_archived_candidate(
                candidate: &Self::Candidate,
            ) -> Vec<#yosoi::__private::PortableCandidateField> {
                vec![#(#portable_candidate_fields),*]
            }

            fn from_archived_record(
                record: &#yosoi::__private::PortableValidatedContractRecord,
            ) -> Result<Self, #yosoi::__private::PortableContractDecodeError> {
                #(#portable_record_decodes)*
                Ok(Self { #(#record_fields),* })
            }
        }

        #[doc(hidden)]
        #visibility struct #extracted_name {
            __inner: #yosoi::ExtractorOutput<#type_name>,
        }

        impl ::std::fmt::Debug for #extracted_name {
            fn fmt(
                &self,
                formatter: &mut ::std::fmt::Formatter<'_>,
            ) -> ::std::fmt::Result {
                formatter
                    .debug_struct("Extracted")
                    .field("candidate_count", &self.__inner.candidates().len())
                    .field("diagnostic_count", &self.__inner.diagnostics().len())
                    .finish_non_exhaustive()
            }
        }

        impl #extracted_name {
            pub fn candidates(&self) -> &[#candidate_name] {
                self.__inner.candidates()
            }

            pub fn diagnostics(&self) -> &[#yosoi::ExtractionDiagnostic] {
                self.__inner.diagnostics()
            }

            pub fn validate(self) -> #yosoi::ContractOutcome<#type_name> {
                self.validate_with_limits(#yosoi::ValidationLimits::default())
            }

            #[doc(hidden)]
            pub fn validate_with_limits(
                self,
                limits: #yosoi::ValidationLimits,
            ) -> #yosoi::ContractOutcome<#type_name> {
                match self.__inner {
                    #yosoi::ExtractorOutput::Candidates {
                        document_id,
                        candidates,
                        diagnostics,
                    } => {
                        let mut budget = match #yosoi::ValidationBudget::preflight::<#type_name>(
                            &candidates,
                            limits,
                        ) {
                            Ok(budget) => budget,
                            Err(failure) => {
                                return #yosoi::ContractOutcome::ValidationRejected { failure };
                            }
                        };
                        let mut records = Vec::new();
                        let mut issues = Vec::new();
                        for candidate in candidates {
                            match #type_name::__ys_validate_candidate(&candidate) {
                                Ok(value) => records.push(#yosoi::ValidatedRecord {
                                    value,
                                    candidate,
                                }),
                                Err(field_drafts) => {
                                    if let Err(failure) = budget.record_issue_drafts(&field_drafts) {
                                        return #yosoi::ContractOutcome::ValidationRejected {
                                            failure,
                                        };
                                    }
                                    let fields = field_drafts
                                        .into_iter()
                                        .map(#yosoi::FieldIssueDraft::materialize)
                                        .collect();
                                    issues.push(#yosoi::RecordIssue { candidate, fields });
                                }
                            }
                        }
                        #yosoi::ContractOutcome::Evaluated {
                            document_id,
                            records,
                            issues,
                            extraction_diagnostics: diagnostics,
                        }
                    }
                    #yosoi::ExtractorOutput::NoMatch { document_id } => {
                        #yosoi::ContractOutcome::NoMatch { document_id }
                    }
                    #yosoi::ExtractorOutput::Indeterminate {
                        document_id,
                        completeness,
                        reason_code,
                    } => #yosoi::ContractOutcome::Indeterminate {
                        document_id,
                        completeness,
                        reason_code,
                    },
                    #yosoi::ExtractorOutput::LocateFailed { failure } => {
                        #yosoi::ContractOutcome::LocateFailed { failure }
                    }
                    #yosoi::ExtractorOutput::Rejected { failure } => {
                        #yosoi::ContractOutcome::ExtractionRejected { failure }
                    }
                }
            }
        }

        impl #type_name {
            const __YS_ROOT_LOCATOR: Option<#yosoi::PinnedLocator> = #root_locator;

            pub fn root_locator() -> Option<#yosoi::PinnedLocator> {
                Self::__YS_ROOT_LOCATOR
            }

            #plan_methods

            fn __ys_validate_candidate(
                candidate: &#candidate_name,
            ) -> Result<Self, Vec<#yosoi::FieldIssueDraft<'_>>> {
                #(#validation_results)*
                let has_issues = false #(|| #issue_flags)*;
                if has_issues {
                    let mut issues = Vec::new();
                    #(#issue_moves)*
                    return Err(issues);
                }
                #(#value_unwraps)*
                Ok(Self { #(#record_fields),* })
            }

            pub fn schema() -> Result<&'static #yosoi::ContractSchema, #yosoi::ContractSchemaError> {
                <Self as #yosoi::Contract>::schema()
            }

            pub fn extract(
                located: &#yosoi::LocateOutcome,
            ) -> #yosoi::Extracted<Self> {
                #extracted_name {
                    __inner: #yosoi::extract_contract::<Self>(located),
                }
            }

            #[doc(hidden)]
            pub fn extract_with_limit(
                located: &#yosoi::LocateOutcome,
                maximum_findings: u64,
            ) -> #yosoi::Extracted<Self> {
                #extracted_name {
                    __inner: #yosoi::extract_contract_with_limit::<Self>(
                        located,
                        maximum_findings,
                    ),
                }
            }
        }
    })
}
