import logging

class ExceptionLogging(object):
    def process_exception(self, request, exception):
        logging.exception('Exception handling request for ' + request.path)