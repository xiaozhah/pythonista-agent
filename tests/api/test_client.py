def test_a_discarded_transport_closes_its_connection() -> None:
    from pycoder.api.client import RequestsTransport

    closed = []

    class Session:
        def close(self) -> None:
            closed.append(True)

    transport = RequestsTransport()
    transport._session = Session()
    del transport
    assert closed == [True]
