from pydantic import BaseModel,Field,EmailStr,field_validator,model_validator
from fastapi import HTTPException,status
from typing import Annotated,Literal,Optional
from datetime import datetime,timezone
from bson import ObjectId
from enum import Enum

def validate_password_strength(value :str) -> str :
    if len(value) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT , detail="Password must contain at least 8 characters.")

    if not any(char.isupper() for char in value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Password must contain at least one uppercase letter.")

    if not any(char.islower() for char in value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Password must contain at least one lowercase letter.")

    if not any(char.isdigit() for char in value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="Password must contain at least one number.")

    if not any(char not in "@#$%&" for char in value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT ,detail="Password must contain at least one special character.")

    return value

class User(BaseModel) :
    id : str
    first_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your First Name",examples=["Max"])]
    last_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your Last Name",examples=["Verstappen"])]
    email : Annotated[EmailStr,Field(...,description="Enter Valid Email",examples=["max123@gmail.com"])]
    password : Annotated[str,Field(...,min_length=8,description="Password contain min 8 char,1 uppercase,1 special character and number",examples=["Max#1234"])]
    createdAt : datetime=Field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt : datetime=Field(default_factory=lambda: datetime.now(timezone.utc))

class Create_user(BaseModel) :
    first_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your First Name",examples=["Max"])]
    last_name : Annotated[str,Field(...,min_length=2,max_length=100,description="Add Your Last Name",examples=["Verstappen"])]
    email : Annotated[EmailStr,Field(...,description="Enter Valid Email",examples=["max123@gmail.com"])]
    password : Annotated[str,Field(...,min_length=8,description="Password contain min 8 char,1 uppercase,1 special character and number",examples=["Max#1234"])]

    @field_validator("password")
    @classmethod
    def check_password(cls,value:str):
       return validate_password_strength(value)
    

class Login_user(BaseModel) :
    email : Annotated[EmailStr,Field(...,description="Enter Valid Email",examples=["max123@gmail.com"])]
    password : Annotated[str,Field(...,min_length=8,description="Password contain min 8 char,1 uppercase,1 special character and number",examples=["Max#1234"])]

class Update_user(BaseModel) :
    first_name: str | None = Field(default=None, min_length=2, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email : EmailStr | None = Field(default=None)

    @model_validator(mode="after")
    def validate_update_field(self) :
        if not self.model_fields_set:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,detail="At least one field must be provided.")

        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")

        return self

class Update_password(BaseModel) :
    oldpassword : Annotated[str,Field(..., examples=["Abc@1234"])]
    newpassword: Annotated[str,Field(..., min_length=8 , examples=["Bac@1234"])]

    @field_validator("newpassword")
    @classmethod
    def check_new_password(cls,value :str) :
        return validate_password_strength(value)

class RefreshTokenRequest(BaseModel):
    refresh_token: Annotated[str, Field(..., min_length=1 , description="Valid refresh token required", examples=["your_refresh_token_here"])]

class CreateConversation(BaseModel):
    title : Annotated[str,Field(...,min_length=2,max_length=200,description="Enter Conversation Title",examples=["Artificial Intelligence(AI)"])]

    @field_validator("title")
    @classmethod
    def validate_title(cls,value :str) :
        value = value.strip()

        if len(value)<2:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT ,detail="Conversation title must contain at least 2 characters.")

        return value


class CreateMessages(BaseModel) :
    content : Annotated[str,Field(...,min_length=1,max_length=1000,description="Enter Your Message",examples=["Type anything you want to say?"])]

    @field_validator("content")
    @classmethod
    def validate_content(cls,value:str) :
        value = value.strip()
        if not value :
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT ,detail="Message cannot contain only whitespace.")
        
        return value

class MessageStatus(str,Enum) :
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"




