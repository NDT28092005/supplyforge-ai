from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.services.ml_model import HybridModelPipeline
from supplyforge.services.shap_service import ShapExplanationService

@api_view(['GET'])
def get_sku_xai(request, workspace_id, sku_id):
    """
    GET /api/v1/workspaces/<workspace_id>/sku/<sku_id>/xai
    Returns:
    - risk_probability (float)
    - base_value (float)
    - model_version (str)
    - shap_contributions (list of dict)
    - ai_explanation (str)
    """
    workspace_id = request.workspace_id

    # 1. Run ML Hybrid Model Prediction (Phase 6)
    pred_result = HybridModelPipeline.predict_risk(sku_id, workspace_id)
    if not pred_result:
        return Response(
            {"error": f"SKU with ID {sku_id} was not found in workspace {workspace_id}."},
            status=status.HTTP_404_NOT_FOUND
        )

    # 2. Run SHAP calculation & natural language copilot interpretation (Phase 7 & 8)
    explanation = ShapExplanationService.explain_prediction(pred_result, sku_id, workspace_id)
    
    return Response(explanation, status=status.HTTP_200_OK)
