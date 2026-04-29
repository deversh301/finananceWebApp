FROM amazon/aws-lambda-python:3.11

# install qpdf (runtime dependency)
RUN yum install -y qpdf

# upgrade pip (VERY IMPORTANT)
RUN pip install --upgrade pip
# dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# code
COPY lambda_function.py .
COPY emailtemplate.html .
COPY services .
COPY helpers .

# command
CMD ["lambda_function.lambda_handler"]