"""Request-scoped, internal-only model output capture (never hidden reasoning)."""
from contextvars import ContextVar
sink=ContextVar('dialogue_model_responses',default=None)

def record(content,model,schema,usage,transport_attempts=None):
    target=sink.get()
    if target is not None:
        target.append({'model':model,'schema':getattr(schema,'__name__','json'),'content':content[:24000],'usage':usage,
                       **({'transport_attempts':list(transport_attempts)} if transport_attempts else {})})
