def get_type(node, is_root=False):
    if is_root:
        return "PROJECT"
    elif node.get("ROOT_DIR_ON_SERVER"):
        return "FILE"
    else:
        return "FOLDER"


def build_metadata(node, node_type):
    if node_type == "PROJECT":
        smTitle = " | ".join(
            filter(None, [node.get("CN_REFERENCE_PROJECT"),node.get("TDM_DESCRIPTION")])
        )
        
        return {
            "Title": smTitle,
            "_x0033_DX_Title": node.get('TITLE'),
            "AdditionnalInformation":node.get('DETAILS'),
            "LastModificationDate": node.get("MODIFICATION_DATE"),
            "SM_Created_Date": node.get("CREATION_DATE"),
            "SM_Created_By": node.get("USER_OBJECT_ID"),
            "SM_Description":node.get("TDMX_COMMENTS"),
        }

    elif node_type == "FOLDER":
        smTitle = " | ".join(
            filter(None, [node.get("TDMX_CAD_IDENTIFIER"),node.get("Description")])
        )
        print("FINAL smTitle:", smTitle)
        return {
            "Title": smTitle,
            "_x0033_DX_Title": node.get("Description"),
            "LastModificationDate": node.get("MODIFICATION_DATE"),
            "SM_Created_Date": node.get("CREATION_DATE"),
            "SM_Created_By": node.get("USER_OBJECT_ID"),
        }

    elif node_type == "FILE":
        smAdditionalDetails = "\n".join([
            f"A/C Applicability : {node.get('CN_DOCUMENT_APPLICABILITY', '')}",
            f"Design Module : {node.get('DESIGN_MODULE', '')}",
            f"Detail : {node.get('TDMX_DETAILED_DESCRIPTION', '')}",
            f"Comments : {node.get('TDMX_COMMENTS', '')}",
        ])
        smTitle = " | ".join(
            filter(None, [node.get("TDMX_CAD_IDENTIFIER")])
        )
        return {
            "Title": node.get("Description"),
            "Revision": node.get("REVISION"),
            "ExternalRevision": node.get("REVISION"),
            "_x0033_DX_Title": smTitle,
            "LastModificationDate": node.get("MODIFICATION_DATE"),
            "SM_Created_Date": node.get("CREATION_DATE"),
            "SM_Created_By": node.get("USER_OBJECT_ID"),
            "State": node.get("STATE"),
            "AdditionnalInformation":smAdditionalDetails,
        }

    return {}