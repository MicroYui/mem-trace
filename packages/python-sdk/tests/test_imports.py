def test_sdk_package_importable() -> None:
    import memtrace_sdk
    from memtrace_sdk import (
        BadRequestError,
        Backend,
        HttpBackend,
        InProcessBackend,
        MemTrace,
        MemTraceLangGraphAdapter,
        MemTraceError,
        NotFoundError,
    )

    assert memtrace_sdk.__all__ == [
        "MemTrace",
        "Backend",
        "InProcessBackend",
        "HttpBackend",
        "MemTraceError",
        "NotFoundError",
        "BadRequestError",
        "MemTraceLangGraphAdapter",
    ]
    assert MemTrace.__name__ == "MemTrace"
    assert MemTraceLangGraphAdapter.__name__ == "MemTraceLangGraphAdapter"
    assert Backend.__name__ == "Backend"
    assert InProcessBackend.__name__ == "InProcessBackend"
    assert HttpBackend.__name__ == "HttpBackend"
    assert issubclass(NotFoundError, MemTraceError)
    assert issubclass(BadRequestError, MemTraceError)
