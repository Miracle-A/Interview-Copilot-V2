# Use the OS certificate store for all TLS (corporate proxies inject their
# own CA). Must run before any library creates an ssl.SSLContext, so it lives
# here: every entry point imports app.* first.
import truststore

truststore.inject_into_ssl()
