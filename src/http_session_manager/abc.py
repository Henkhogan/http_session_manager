from abc import ABC, abstractmethod

class AbstractSessionManager(ABC):
    
    @abstractmethod
    def __aenter__(self):
        return self

    @abstractmethod
    def __aexit__(self, exc_t, exc_v, exc_tb):
        pass


    @abstractmethod
    def get_session(self, session_id):
        pass
    
    @abstractmethod
    def create_session(self, session_id):
        pass
    
    @abstractmethod
    def delete_session(self, session_id):
        pass
    
    @abstractmethod
    def update_session(self, session_id, session):
        pass
    
    @abstractmethod
    def get_all_sessions(self):
        pass